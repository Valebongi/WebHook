"""Capa de acceso a SQL Server.

Expone:
  - `get_engine()`: SQLAlchemy engine con pool y keepalive.
  - `get_connection()`: context manager de pyodbc con transacción.
  - queries de lookup, dedupe y inserción para el pipeline de creación de
    oportunidad que replica lo que hace el SP_ProcessLinkedinCorrectos.
"""

import logging
import re
import unicodedata
from contextlib import contextmanager
from difflib import SequenceMatcher
from typing import Optional

import pyodbc
from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from config import DB_CONFIG

logger = logging.getLogger(__name__)


_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
_SPACE_RE = re.compile(r"\s+")
_STOPWORDS = {
    "de", "del", "la", "las", "el", "los", "y", "e", "en", "con", "para",
    "por", "a", "al", "un", "una", "the", "and", "or",
}
_PREFIXES = {
    "pep", "pae", "cep",
}


def _normalize_nombre_producto(value: str) -> str:
    """Normaliza texto para comparar nombres con ruido editorial."""
    txt = (value or "").strip().lower()
    if not txt:
        return ""
    txt = "".join(
        c for c in unicodedata.normalize("NFD", txt)
        if unicodedata.category(c) != "Mn"
    )
    txt = _PUNCT_RE.sub(" ", txt)
    txt = _SPACE_RE.sub(" ", txt).strip()
    return txt


def _tokenize_nombre(value: str) -> list[str]:
    tokens = []
    for tok in _normalize_nombre_producto(value).split():
        if len(tok) <= 2:
            continue
        if tok in _STOPWORDS or tok in _PREFIXES:
            continue
        tokens.append(tok)
    return tokens


def _score_nombre_match(input_nombre: str, candidate_nombre: str) -> float:
    """Score heurístico [0..1] entre nombre entrante y nombre de catálogo."""
    in_norm = _normalize_nombre_producto(input_nombre)
    cand_norm = _normalize_nombre_producto(candidate_nombre)
    if not in_norm or not cand_norm:
        return 0.0

    if in_norm == cand_norm:
        return 1.0

    in_tokens = set(_tokenize_nombre(in_norm))
    cand_tokens = set(_tokenize_nombre(cand_norm))
    token_overlap = 0.0
    if in_tokens and cand_tokens:
        token_overlap = len(in_tokens & cand_tokens) / len(in_tokens | cand_tokens)

    contains_bonus = 0.0
    if in_norm in cand_norm or cand_norm in in_norm:
        contains_bonus = 0.2

    seq_ratio = SequenceMatcher(None, in_norm, cand_norm).ratio()
    score = (0.55 * token_overlap) + (0.45 * seq_ratio) + contains_bonus
    return min(score, 1.0)


def _lookup_diccionario_form_name(conn, db_name: str, nombre: str) -> Optional[dict]:
    """Busca una corrección en adm.DiccionarioFormName por nombre normalizado.

    La tabla existe en producción y QA. La reutilizamos como diccionario de
    alias editoriales de formularios: si el `Error` coincide, devolvemos el
    `Correcto` para seguir resolviendo el producto.
    """
    tbl = f"[{db_name}].adm.DiccionarioFormName"
    sql = text(
        f"""
        SELECT Error, Correcto
        FROM {tbl}
        WHERE Activo = 1
        ORDER BY Id DESC
        """
    )
    try:
        target = _normalize_nombre_producto(nombre)
        if not target:
            return None
        rows = conn.execute(sql).mappings().all()
        best_row = None
        best_len = -1
        for row in rows:
            error_norm = _normalize_nombre_producto(row.get("Error") or "")
            if not error_norm:
                continue
            if error_norm == target or error_norm in target or target in error_norm:
                if len(error_norm) > best_len:
                    best_row = row
                    best_len = len(error_norm)
        return dict(best_row) if best_row else None
    except SQLAlchemyError as exc:
        logger.warning("Error consultando DiccionarioFormName en %s: %s", db_name, exc)
        return None


def _search_producto_por_token_exacto(conn, db_name: str, token: str) -> Optional[dict]:
    """Busca un producto por token exacto en Nombre, CodigoLanzamiento o CodigoLinkedin."""
    tbl = f"[{db_name}].adm.Producto"
    sql = text(
        f"""
        SELECT TOP (1) Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase
        FROM {tbl}
        WHERE (
            LTRIM(RTRIM(Nombre)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(:token)) COLLATE DATABASE_DEFAULT
            OR LTRIM(RTRIM(CodigoLanzamiento)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(:token)) COLLATE DATABASE_DEFAULT
            OR LTRIM(RTRIM(CodigoLinkedin)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(:token)) COLLATE DATABASE_DEFAULT
        )
          AND Estado = 1
        ORDER BY Id DESC
        """
    )
    row = conn.execute(sql, {"token": token}).mappings().first()
    if not row:
        return None
    d = dict(row)
    d["_match_step"] = "exacto_token"
    d["_db"] = db_name
    return d


def _search_producto_fuzzy_en_db(conn, db_name: str, nombre: str) -> Optional[dict]:
    """Fallback tolerante para variaciones de naming en formularios de WP."""
    from config import ESTADO_PRODUCTO_TIPOS_PERMITIDOS

    tbl = f"[{db_name}].adm.Producto"
    sql = text(
        f"""
        SELECT Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase
        FROM {tbl}
        WHERE Estado = 1
          AND EstadoProductoTipoId IN :tipos
        ORDER BY Id DESC
        """
    ).bindparams(bindparam("tipos", expanding=True))

    rows = conn.execute(sql, {"tipos": list(ESTADO_PRODUCTO_TIPOS_PERMITIDOS)}).mappings().all()
    if not rows:
        return None

    best_row = None
    best_score = 0.0
    for row in rows:
        score = _score_nombre_match(nombre, row.get("Nombre") or "")
        if score > best_score:
            best_score = score
            best_row = row

    # Umbral conservador para evitar matches incorrectos.
    if not best_row or best_score < 0.62:
        return None

    d = dict(best_row)
    d["_match_step"] = "fuzzy"
    d["_match_score"] = round(best_score, 4)
    d["_db"] = db_name
    return d


def _build_sqlalchemy_url() -> str:
    driver = DB_CONFIG["driver"].replace(" ", "+")
    return (
        f"mssql+pyodbc://{DB_CONFIG['username']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['server']}/{DB_CONFIG['database']}"
        f"?driver={driver}&TrustServerCertificate=yes"
    )


def _build_pyodbc_conn_str() -> str:
    return (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['username']};"
        f"PWD={DB_CONFIG['password']};"
        "TrustServerCertificate=yes;"
    )


_engine = None


def get_engine():
    """Devuelve un engine singleton. Reutilizable entre requests."""
    global _engine
    if _engine is None:
        try:
            _engine = create_engine(
                _build_sqlalchemy_url(),
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_reset_on_return="rollback",
            )
            with _engine.connect() as c:
                c.execute(text("SELECT 1"))
            logger.info("SQLAlchemy engine listo → %s/%s",
                        DB_CONFIG['server'], DB_CONFIG['database'])
        except SQLAlchemyError as exc:
            logger.error("No se pudo conectar a la BD: %s", exc)
            raise
    return _engine


@contextmanager
def get_connection():
    """Context manager que abre una conexión pyodbc con transacción manual."""
    conn = pyodbc.connect(_build_pyodbc_conn_str(), autocommit=False)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Lookups ───────────────────────────────────────────────────────────────────

def _search_producto_en_db(conn, db_name: str, nombre: str) -> Optional[dict]:
    """Busca un Producto activo con `EstadoProductoTipoId` permitido dentro de `db_name`.

    Estrategia en tres pasos, retornando el primer match encontrado:
      1. Match exacto (LTRIM/RTRIM + COLLATE DATABASE_DEFAULT).
      2. Match por prefijo (`LIKE 'texto%'`). Útil cuando el form manda el
         nombre base y BD tiene sufijo, p.ej.:
           form → "PEP Supervisor en Mantenimiento"
           BD   → "PEP Supervisor en Mantenimiento - Febrero"
      3. Match por substring (`LIKE '%texto%'`). Útil cuando el form omite
         prefijos tipo "CEP"/"PAE"/"PEP" que sí lleva el nombre en BD:
           form → "Analista de Datos con Power BI y Python"
           BD   → "CEP Analista de Datos con Power BI y Python"

    En los 3 pasos filtra por `Estado=1` y `EstadoProductoTipoId IN (17,19,20)`.
    Si varios productos coinciden, devuelve el de mayor `Id` (más reciente).
    """
    from config import ESTADO_PRODUCTO_TIPOS_PERMITIDOS

    tbl = f"[{db_name}].adm.Producto"
    safe = (
        nombre.replace("[", "[[]")
              .replace("%", "[%]")
              .replace("_", "[_]")
    )
    steps = [
        ("exacto",
         "LTRIM(RTRIM(Nombre)) COLLATE DATABASE_DEFAULT = LTRIM(RTRIM(:nombre)) COLLATE DATABASE_DEFAULT",
         {"nombre": nombre}),
        ("prefijo",
         "Nombre COLLATE DATABASE_DEFAULT LIKE :pat COLLATE DATABASE_DEFAULT",
         {"pat": safe + "%"}),
        ("substring",
         "Nombre COLLATE DATABASE_DEFAULT LIKE :pat COLLATE DATABASE_DEFAULT",
         {"pat": "%" + safe + "%"}),
    ]
    for label, where_name, extra_params in steps:
        sql = text(
            f"""
            SELECT TOP (1)
                   Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase
            FROM {tbl}
            WHERE {where_name}
              AND Estado = 1
              AND EstadoProductoTipoId IN :tipos
            ORDER BY Id DESC
            """
        ).bindparams(bindparam("tipos", expanding=True))
        row = conn.execute(
            sql,
            {**extra_params, "tipos": list(ESTADO_PRODUCTO_TIPOS_PERMITIDOS)},
        ).mappings().first()
        if row:
            d = dict(row)
            d["_match_step"] = label
            d["_db"] = db_name
            return d
    return None


def _search_producto_por_nombre_exacto(conn, db_name: str, nombre_exacto: str) -> Optional[dict]:
    """Busca un Producto por Nombre exactamente igual. Solo activos.

    A diferencia de `_search_producto_en_db`, NO aplica el filtro de
    `EstadoProductoTipoId`: lo que queremos es que coincida el Id local del
    catálogo autoritativo, aunque localmente tenga TipoId distinto.
    """
    tbl = f"[{db_name}].adm.Producto"
    sql = text(
        f"""
        SELECT TOP (1) Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase
        FROM {tbl}
        WHERE LTRIM(RTRIM(Nombre)) COLLATE DATABASE_DEFAULT
              = LTRIM(RTRIM(:nombre)) COLLATE DATABASE_DEFAULT
          AND Estado = 1
        ORDER BY Id DESC
        """
    )
    row = conn.execute(sql, {"nombre": nombre_exacto}).mappings().first()
    return dict(row) if row else None


def fetch_producto_por_nombre(nombre: str) -> Optional[dict]:
    """Encuentra el producto para una Oportunidad nueva desde el form de WP.

    Flujo:
      1. Busca en `PRODUCTS_DB_NAME` (catálogo autoritativo — en testing
         apuntamos a OlympusDB real; en prod será igual a DB_NAME) usando
         los 3 pasos exacto/prefijo/substring.
      2. Si `PRODUCTS_DB_NAME == DB_NAME` (prod típico) devuelve el row tal
         cual — el Id es válido para la FK de `Oportunidad`.
      3. Si son distintas (testing cross-DB), toma el `Nombre` encontrado
         en el catálogo y hace un **segundo lookup exacto** en la DB local
         (`DB_NAME`) para obtener el Id local — necesario para respetar la
         FK `FK_Oportunidad_Producto`. Si ese producto no existe localmente
         devuelve un marker especial `{"_sync_missing": True, ...}` para que
         el servicio mande el lead a pendientes con motivo claro.

    Returns:
        - dict con producto válido (incluye Id local) para crear oportunidad,
        - dict con `_sync_missing=True` si falta sincronizar en la DB local,
        - None si no se encontró en ningún catálogo.
    """
    from config import DB_CONFIG, PRODUCTS_DB_NAME

    clean = (nombre or "").strip()
    if not clean:
        return None

    local_db = DB_CONFIG["database"]
    try:
        with get_engine().connect() as conn:
            # Paso 0: diccionario de alias editoriales / formas del formulario.
            alias = _lookup_diccionario_form_name(conn, PRODUCTS_DB_NAME, clean)
            if alias and alias.get("Correcto"):
                clean = (alias["Correcto"] or "").strip() or clean
                logger.info(
                    "Nombre '%s' resuelto via DiccionarioFormName -> '%s'",
                    nombre, clean,
                )

            # Paso 1: buscar en catálogo autoritativo por token exacto o patrón.
            catalogo = _search_producto_por_token_exacto(conn, PRODUCTS_DB_NAME, clean)
            if not catalogo:
                catalogo = _search_producto_en_db(conn, PRODUCTS_DB_NAME, clean)
            if not catalogo:
                catalogo = _search_producto_fuzzy_en_db(conn, PRODUCTS_DB_NAME, clean)
            if not catalogo:
                return None

            logger.info(
                "Producto en catálogo (%s) paso=%s score=%s id=%s nombre='%s' (buscado: '%s')",
                PRODUCTS_DB_NAME, catalogo.get("_match_step", "desconocido"),
                catalogo.get("_match_score"),
                catalogo["Id"], catalogo["Nombre"], clean,
            )

            # Paso 2: caso simple — misma DB
            if PRODUCTS_DB_NAME == local_db:
                return catalogo

            # Paso 3: cross-DB. Necesitamos el Id local para la FK.
            local = _search_producto_por_nombre_exacto(
                conn, local_db, catalogo["Nombre"],
            )
            if local:
                # Usamos TODOS los campos del registro local para mantener
                # consistencia entre Id y demás campos (la Oportunidad guardará
                # CodigoLanzamiento que debe coincidir con el producto local).
                return local
            # Producto existe en catálogo pero no en DB local → hay que sincronizar
            return {
                "_sync_missing":    True,
                "catalogo_db":      PRODUCTS_DB_NAME,
                "local_db":         local_db,
                "Id":               catalogo["Id"],  # Id del catálogo, NO usar para FK
                "Nombre":           catalogo["Nombre"],
                "CodigoLanzamiento": catalogo.get("CodigoLanzamiento"),
                "CodigoLinkedin":   catalogo.get("CodigoLinkedin"),
                "CostoBase":        catalogo.get("CostoBase"),
            }
    except SQLAlchemyError as exc:
        logger.error("Error buscando producto '%s': %s", nombre, exc)
        raise


def fetch_pais_por_prefijo(prefijo_sin_mas: int) -> Optional[dict]:
    """Fallback: busca un país por su prefijo numérico (sin el +)."""
    sql = text(
        """
        SELECT TOP (1) Id, Nombre, PrefijoCelularPais
        FROM mdm.Pais
        WHERE PrefijoCelularPais = :pref
        """
    )
    try:
        with get_engine().connect() as conn:
            row = conn.execute(sql, {"pref": prefijo_sin_mas}).mappings().first()
        return dict(row) if row else None
    except SQLAlchemyError as exc:
        logger.warning("Error buscando país por prefijo=%s: %s", prefijo_sin_mas, exc)
        return None


def fetch_producto_generico(
    producto_id: int | None,
    codigo_lanzamiento: str,
) -> Optional[dict]:
    """Busca un producto activo para el endpoint genérico.

    Prioridad:
      1. `producto_id` si está configurado.
      2. `codigo_lanzamiento` como fallback.
    """
    sql_by_id = text(
        """
        SELECT TOP (1) Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase
        FROM adm.Producto
        WHERE Id = :id
          AND Estado = 1
        """
    )
    sql_by_cl = text(
        """
        SELECT TOP (1) Id, Nombre, CodigoLanzamiento, CodigoLinkedin, CostoBase
        FROM adm.Producto
        WHERE CodigoLanzamiento COLLATE DATABASE_DEFAULT = :cl COLLATE DATABASE_DEFAULT
          AND Estado = 1
        ORDER BY Id DESC
        """
    )
    try:
        with get_engine().connect() as conn:
            if producto_id is not None:
                row = conn.execute(sql_by_id, {"id": producto_id}).mappings().first()
                if row:
                    return dict(row)

            clean_cl = (codigo_lanzamiento or "").strip()
            if clean_cl:
                row = conn.execute(sql_by_cl, {"cl": clean_cl}).mappings().first()
                if row:
                    return dict(row)
        return None
    except SQLAlchemyError as exc:
        logger.error(
            "Error buscando producto genérico (id=%s, cl=%s): %s",
            producto_id,
            codigo_lanzamiento,
            exc,
        )
        raise


# ── Dedupe ────────────────────────────────────────────────────────────────────

def exists_oportunidad_activa(email: str, codigo_lanzamiento: str) -> Optional[int]:
    """Replica la regla de dedupe del SP.

    Devuelve el Id de la oportunidad si ya existe una opp con el mismo email y
    producto cuyo último HistorialEstado esté en (1,3,4,5,6). None si no.
    """
    from config import ESTADOS_QUE_BLOQUEAN_NUEVA_OPP

    if not email:
        return None
    sql = text(
        """
        SELECT TOP (1) o.Id
        FROM adm.Oportunidad o
        INNER JOIN adm.PotencialCliente pc ON pc.Id = o.IdPotencialCliente
        INNER JOIN adm.Persona per         ON per.Id = pc.IdPersona
        CROSS APPLY (
            SELECT TOP (1) he.IdEstado
            FROM adm.HistorialEstado he
            WHERE he.IdOportunidad = o.Id
            ORDER BY he.FechaCreacion DESC, he.Id DESC
        ) heLast
        WHERE LTRIM(RTRIM(per.Correo)) COLLATE DATABASE_DEFAULT
              = LTRIM(RTRIM(:email)) COLLATE DATABASE_DEFAULT
          AND o.CodigoLanzamiento COLLATE DATABASE_DEFAULT
              = :cl COLLATE DATABASE_DEFAULT
          AND o.Estado = 1
          AND heLast.IdEstado IN :estados
        """
    ).bindparams(bindparam("estados", expanding=True))
    try:
        with get_engine().connect() as conn:
            row = conn.execute(
                sql,
                {
                    "email":   email,
                    "cl":      codigo_lanzamiento,
                    "estados": list(ESTADOS_QUE_BLOQUEAN_NUEVA_OPP),
                },
            ).first()
        return int(row[0]) if row else None
    except SQLAlchemyError as exc:
        logger.error("Error en dedupe (email=%s, cl=%s): %s", email, codigo_lanzamiento, exc)
        raise
