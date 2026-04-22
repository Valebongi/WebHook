"""Reproduce en Python el pipeline de inserción que hace `SPImportarLinkedinCorrectos`.

Todo ocurre dentro de una única transacción pyodbc; si cualquier paso falla,
se hace rollback y no queda basura parcial en la BD.

Pasos:
  1. Buscar o crear `adm.Persona` (match por Correo o por Prefijo+Celular).
  2. Buscar o crear `adm.PotencialCliente` (uno por Persona).
  3. Calcular auto-asignación de asesor (última opp abierta con asesor activo).
  4. Insertar `adm.Oportunidad`.
  5. Insertar `adm.HistorialEstado` inicial (IdEstado=1).
  6. Si hubo auto-asignación, updatear HistorialEstado.IdPersonal.
  7. Insertar `adm.Inversion` con Producto.CostoBase.
  8. Log en `adm.OportunidadAutoAsignacionLog` si aplicó auto-asignación.

No requiere tablas propias del módulo; todos los INSERT van a las mismas
tablas que usa el SP existente.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import pyodbc

from config import (
    AUDIT_USER,
    DEFAULT_IDASESOR,
    DEFAULT_IDESTADO_INICIAL,
    DEFAULT_IDOCURRENCIA,
    OPORTUNIDAD_ORIGEN,
)

logger = logging.getLogger(__name__)


@dataclass
class OpportunityInput:
    """Input normalizado para crear una oportunidad desde el form de WP."""
    nombres:            str
    apellidos:          str
    email:              str
    codigo_pais:        str          # "+57"
    celular:            str          # "310 456 7890"
    id_pais:            Optional[int]
    producto_id:        int
    codigo_lanzamiento: str
    costo_base:         Optional[float]
    fecha_formulario:   Optional[datetime]


@dataclass
class OpportunityResult:
    oportunidad_id:       int
    persona_id:           int
    potencial_cliente_id: int
    historial_id:         int
    inversion_id:         Optional[int]
    auto_assigned_personal_id: Optional[int]


def create_opportunity(conn: pyodbc.Connection, inp: OpportunityInput) -> OpportunityResult:
    """Ejecuta todo el pipeline dentro de la conexión/transacción provista."""
    cur = conn.cursor()
    now = datetime.now()

    # ── 1) Persona: match por correo o por prefijo+celular ────────────────────
    persona_id = _find_persona(cur, inp.email, inp.codigo_pais, inp.celular)
    if persona_id is None:
        persona_id = _insert_persona(cur, inp, now)
        logger.info("Persona creada Id=%s (email=%s)", persona_id, inp.email)
    else:
        logger.info("Persona existente Id=%s reutilizada (email=%s)", persona_id, inp.email)

    # ── 2) PotencialCliente ──────────────────────────────────────────────────
    pc_id = _find_potencial_cliente(cur, persona_id)
    if pc_id is None:
        pc_id = _insert_potencial_cliente(cur, persona_id, now)

    # ── 3) Auto-asignación de asesor ─────────────────────────────────────────
    prior = _find_prior_auto_assignment(cur, pc_id, inp.codigo_lanzamiento)

    # ── 4) Oportunidad ───────────────────────────────────────────────────────
    opp_id = _insert_oportunidad(
        cur,
        pc_id=pc_id,
        producto_id=inp.producto_id,
        codigo_lanzamiento=inp.codigo_lanzamiento,
        fecha_formulario=inp.fecha_formulario or now,
        now=now,
        id_personal=prior["PriorIdPersonal"] if prior else None,
    )

    # ── 5) HistorialEstado inicial ───────────────────────────────────────────
    historial_id = _insert_historial_estado(
        cur,
        opp_id=opp_id,
        now=now,
        id_personal=prior["PriorIdPersonal"] if prior else None,
    )

    # ── 6) Log de auto-asignación (si aplicó) ────────────────────────────────
    if prior:
        _insert_auto_assign_log(
            cur,
            opp_id=opp_id,
            now=now,
            new_personal_id=prior["PriorIdPersonal"],
            prior_opp_id=prior["PriorOportunidadId"],
            prior_personal_id=prior["PriorIdPersonal"],
        )

    # ── 7) Inversion ─────────────────────────────────────────────────────────
    inversion_id = None
    if inp.costo_base is not None:
        inversion_id = _insert_inversion(
            cur,
            opp_id=opp_id,
            producto_id=inp.producto_id,
            costo_base=inp.costo_base,
            now=now,
        )

    return OpportunityResult(
        oportunidad_id       = opp_id,
        persona_id           = persona_id,
        potencial_cliente_id = pc_id,
        historial_id         = historial_id,
        inversion_id         = inversion_id,
        auto_assigned_personal_id = prior["PriorIdPersonal"] if prior else None,
    )


# ── Helpers por paso ──────────────────────────────────────────────────────────

def _find_persona(cur: pyodbc.Cursor, email: str, codigo_pais: str, celular: str) -> Optional[int]:
    """Busca Persona existente por correo o por (prefijo + celular).

    Prioriza match por correo (igual que el SP: `ORDER BY CASE WHEN Correo<>''
    THEN 0 ELSE 1 END`).
    """
    cur.execute(
        """
        SELECT TOP (1) p.Id
        FROM adm.Persona p
        WHERE (LEN(?) > 0 AND
               LTRIM(RTRIM(ISNULL(p.Correo,''))) COLLATE DATABASE_DEFAULT
               = LTRIM(RTRIM(?)) COLLATE DATABASE_DEFAULT)
           OR (LEN(?) > 0 AND
               LTRIM(RTRIM(ISNULL(p.PrefijoPaisCelular,''))) COLLATE DATABASE_DEFAULT = ?
               AND LTRIM(RTRIM(ISNULL(p.Celular,''))) COLLATE DATABASE_DEFAULT
                   = LTRIM(RTRIM(?)) COLLATE DATABASE_DEFAULT)
        ORDER BY
            CASE WHEN LTRIM(RTRIM(ISNULL(p.Correo,''))) <> '' THEN 0 ELSE 1 END,
            p.Id
        """,
        email, email, codigo_pais, codigo_pais, celular,
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _insert_persona(cur: pyodbc.Cursor, inp: OpportunityInput, now: datetime) -> int:
    cur.execute(
        """
        INSERT INTO adm.Persona
            (IdPais, Nombres, Apellidos, Celular, PrefijoPaisCelular, Correo, Estado,
             FechaCreacion, UsuarioCreacion, FechaModificacion, UsuarioModificacion, IdMigracion)
        OUTPUT inserted.Id
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, NULL)
        """,
        inp.id_pais,
        (inp.nombres or "")[:255],
        (inp.apellidos or "")[:255],
        (inp.celular or "")[:50],
        (inp.codigo_pais or "")[:20],
        (inp.email or "")[:255],
        now, AUDIT_USER, now, AUDIT_USER,
    )
    row = cur.fetchone()
    return int(row[0])


def _find_potencial_cliente(cur: pyodbc.Cursor, persona_id: int) -> Optional[int]:
    cur.execute(
        "SELECT TOP (1) Id FROM adm.PotencialCliente WHERE IdPersona = ?",
        persona_id,
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _insert_potencial_cliente(cur: pyodbc.Cursor, persona_id: int, now: datetime) -> int:
    cur.execute(
        """
        INSERT INTO adm.PotencialCliente
            (IdPersona, Desuscrito, Estado,
             FechaCreacion, UsuarioCreacion, FechaModificacion, UsuarioModificacion, IdMigracion)
        OUTPUT inserted.Id
        VALUES (?, 0, 1, ?, ?, ?, ?, NULL)
        """,
        persona_id, now, AUDIT_USER, now, AUDIT_USER,
    )
    row = cur.fetchone()
    return int(row[0])


def _find_prior_auto_assignment(cur: pyodbc.Cursor, pc_id: int, codigo_lanzamiento: str) -> Optional[dict]:
    """Busca última oportunidad de este PotencialCliente con asesor activo
    en otro CodigoLanzamiento, para heredar el IdPersonal. Mismo criterio
    que el SP (estados 1/4/5/6 y personal con Cesado=0, Estado=1).
    """
    cur.execute(
        """
        SELECT TOP (1)
               po.Id                                AS PriorOportunidadId,
               ISNULL(po.IdPersonal, he.IdPersonal) AS PriorIdPersonal,
               he.Id                                AS PriorHistorialId
        FROM adm.Oportunidad po
        INNER JOIN adm.HistorialEstado he
               ON he.IdOportunidad = po.Id
              AND he.IdEstado IN (1,4,5,6)
        INNER JOIN adm.Personal pers
               ON pers.Id = ISNULL(po.IdPersonal, he.IdPersonal)
              AND pers.Cesado = 0
              AND pers.Estado = 1
        WHERE po.IdPotencialCliente = ?
          AND po.CodigoLanzamiento <> ?
          AND ISNULL(po.IdPersonal, he.IdPersonal) IS NOT NULL
        ORDER BY he.FechaCreacion DESC, po.FechaCreacion DESC
        """,
        pc_id, codigo_lanzamiento,
    )
    row = cur.fetchone()
    if not row:
        return None
    return {
        "PriorOportunidadId": int(row[0]),
        "PriorIdPersonal":    int(row[1]),
        "PriorHistorialId":   int(row[2]) if row[2] is not None else None,
    }


def _insert_oportunidad(
    cur: pyodbc.Cursor,
    pc_id: int,
    producto_id: int,
    codigo_lanzamiento: str,
    fecha_formulario: datetime,
    now: datetime,
    id_personal: Optional[int],
) -> int:
    cur.execute(
        """
        INSERT INTO adm.Oportunidad
            (IdPotencialCliente, IdProducto, CodigoLanzamiento, Origen, Estado,
             FechaFormulario, FechaCreacion, UsuarioCreacion,
             FechaModificacion, UsuarioModificacion, IdMigracion, IdPersonal)
        OUTPUT inserted.Id
        VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?, NULL, ?)
        """,
        pc_id, producto_id, codigo_lanzamiento, OPORTUNIDAD_ORIGEN,
        fecha_formulario, now, AUDIT_USER, now, AUDIT_USER, id_personal,
    )
    row = cur.fetchone()
    return int(row[0])


def _insert_historial_estado(
    cur: pyodbc.Cursor,
    opp_id: int,
    now: datetime,
    id_personal: Optional[int],
) -> int:
    cur.execute(
        """
        INSERT INTO adm.HistorialEstado
            (IdOportunidad, IdAsesor, IdEstado, IdOcurrencia, IdPersonal, Observaciones,
             CantidadLlamadasContestadas, CantidadLlamadasNoContestadas,
             Estado, FechaCreacion, UsuarioCreacion, FechaModificacion, UsuarioModificacion)
        OUTPUT inserted.Id
        VALUES (?, ?, ?, ?, ?, N'Registrado (importado desde formulario Wordpress)',
                0, 0, 1, ?, ?, ?, ?)
        """,
        opp_id, DEFAULT_IDASESOR, DEFAULT_IDESTADO_INICIAL, DEFAULT_IDOCURRENCIA,
        id_personal, now, AUDIT_USER, now, AUDIT_USER,
    )
    row = cur.fetchone()
    return int(row[0])


def _insert_inversion(
    cur: pyodbc.Cursor,
    opp_id: int,
    producto_id: int,
    costo_base: float,
    now: datetime,
) -> int:
    # Schema real de adm.Inversion (verificado en QA): no tiene columna `Moneda`
    # sino `IdMoneda` (FK a adm.Moneda, 4 = USD). `Cupo` es NOT NULL y no tiene
    # default visible; se inserta 0 igual que las filas creadas por el SP.
    from config import DEFAULT_ID_MONEDA_USD
    cur.execute(
        """
        INSERT INTO adm.Inversion
            (IdProducto, IdOportunidad, CostoTotal, IdMoneda, DescuentoPorcentaje,
             CostoOfrecido, Cupo, Estado, IdMigracion,
             FechaCreacion, UsuarioCreacion, FechaModificacion, UsuarioModificacion)
        OUTPUT inserted.Id
        VALUES (?, ?, ?, ?, NULL, ?, 0, 1, NULL, ?, ?, ?, ?)
        """,
        producto_id, opp_id, costo_base, DEFAULT_ID_MONEDA_USD, costo_base,
        now, AUDIT_USER, now, AUDIT_USER,
    )
    row = cur.fetchone()
    return int(row[0]) if row else None


def _insert_auto_assign_log(
    cur: pyodbc.Cursor,
    opp_id: int,
    now: datetime,
    new_personal_id: int,
    prior_opp_id: int,
    prior_personal_id: int,
) -> None:
    cur.execute(
        """
        INSERT INTO adm.OportunidadAutoAsignacionLog
            (OportunidadId, SourceId, FechaAsignacion, IdPersonalAsignado,
             PriorOportunidadId, PriorIdPersonal, UsuarioAsignacion, Observacion)
        VALUES (?, NULL, ?, ?, ?, ?, ?, N'Auto-asignacion por Wordpress-Lead-API')
        """,
        opp_id, now, new_personal_id, prior_opp_id, prior_personal_id, AUDIT_USER,
    )


def insert_lead_pendiente(
    cur: pyodbc.Cursor,
    nombre_capacitacion: str,
    nombres: str,
    apellidos: str,
    email: str,
    telefono_raw: str,
    id_pais: Optional[int],
    codigo_pais: Optional[str],
    celular: Optional[str],
    form_id: Optional[int],
    fecha_formulario: Optional[datetime],
    motivo: str,
) -> int:
    """Guarda en `adm.Wordpress_Lead_Pendiente` los leads sin match de producto."""
    now = datetime.now()
    cur.execute(
        """
        INSERT INTO adm.Wordpress_Lead_Pendiente
            (NombreCapacitacion, Nombres, Apellidos, Email, Telefono,
             IdPais, CodigoPais, Celular, FormId, FechaFormulario,
             MotivoPendiente, Estado,
             FechaCreacion, UsuarioCreacion, FechaModificacion, UsuarioModificacion)
        OUTPUT inserted.Id
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        """,
        nombre_capacitacion[:300],
        (nombres or "")[:255],
        (apellidos or "")[:255],
        (email or "")[:255],
        (telefono_raw or "")[:40],
        id_pais,
        (codigo_pais or "")[:20] if codigo_pais else None,
        (celular or "")[:50] if celular else None,
        form_id,
        fecha_formulario,
        motivo[:300],
        now, AUDIT_USER, now, AUDIT_USER,
    )
    row = cur.fetchone()
    return int(row[0])
