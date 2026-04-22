"""Orquestador de alto nivel del endpoint POST /leads.

Se encarga de:
  1. Normalizar el payload (split de nombre, parseo de teléfono).
  2. Resolver país desde el prefijo del teléfono.
  3. Resolver Producto por nombre_capacitacion.
  4. Aplicar dedupe por email + CodigoLanzamiento.
  5. Crear la oportunidad dentro de una transacción.
  6. Si no hay producto match, encolar en Wordpress_Lead_Pendiente.

Devuelve un dict con la forma:
  - {"result": "created", ...}
  - {"result": "pending", ...}
  - {"result": "duplicate", ...}
  - {"result": "invalid", "reason": ...}  (errores recoverables)

Errores no-recoverables se dejan propagar como excepciones (el endpoint los
traduce a HTTP 5xx).
"""

import logging
from typing import Any

from db_connector import (
    exists_oportunidad_activa,
    fetch_pais_por_prefijo,
    fetch_producto_por_nombre,
    get_connection,
)
from models.wordpress_lead import WordpressLeadPayload
from services.opportunity_builder import (
    OpportunityInput,
    create_opportunity,
    insert_lead_pendiente,
)
from validators.form_validator import parse_phone, split_full_name

logger = logging.getLogger(__name__)


def _producto_brief(producto: dict) -> dict:
    """Subconjunto del producto que se expone al request-log / clientes."""
    return {
        "Id":                int(producto["Id"]),
        "Nombre":             producto["Nombre"],
        "CodigoLanzamiento":  producto.get("CodigoLanzamiento"),
        "CodigoLinkedin":     producto.get("CodigoLinkedin"),
        "CostoBase":          float(producto["CostoBase"]) if producto.get("CostoBase") is not None else None,
    }


def process_wordpress_lead(payload: WordpressLeadPayload) -> dict[str, Any]:
    """Procesa un lead del form de WordPress. Ver docstring del módulo."""
    # ── 1) Normalización ──────────────────────────────────────────────────────
    name_split = split_full_name(payload.nombres_apellidos)
    phone = parse_phone(payload.telefono)

    if phone is None:
        # Teléfono inválido → no podemos crear oportunidad. Guardamos en
        # pendientes para que alguien lo corrija manualmente.
        return _save_as_pending_minimal(
            payload=payload,
            nombres=name_split.nombres,
            apellidos=name_split.apellidos,
            motivo="Teléfono no parseable con phonenumbers",
        )

    # ── 2) País desde el prefijo ─────────────────────────────────────────────
    prefijo_num = int(phone.codigo_pais.lstrip("+"))
    pais_row = fetch_pais_por_prefijo(prefijo_num)
    id_pais = int(pais_row["Id"]) if pais_row else None

    # ── 3) Producto ───────────────────────────────────────────────────────────
    producto = fetch_producto_por_nombre(payload.nombre_capacitacion)
    if producto is None:
        return _save_as_pending_full(
            payload=payload,
            nombres=name_split.nombres,
            apellidos=name_split.apellidos,
            id_pais=id_pais,
            codigo_pais=phone.codigo_pais,
            celular=phone.celular,
            motivo=(
                "Sin match en adm.Producto (Nombre, Estado=1, "
                "EstadoProductoTipoId en 17/19/20)"
            ),
        )
    if producto.get("_sync_missing"):
        # El producto existe en el catálogo autoritativo pero no en la DB local.
        # No podemos crear la Oportunidad (FK) sin sincronizar primero.
        motivo = (
            f"Producto '{producto['Nombre']}' existe en catálogo "
            f"({producto['catalogo_db']}) pero no en DB local ({producto['local_db']}). "
            "Sincronizar catálogo antes de reintentar."
        )
        outcome = _save_as_pending_full(
            payload=payload,
            nombres=name_split.nombres,
            apellidos=name_split.apellidos,
            id_pais=id_pais,
            codigo_pais=phone.codigo_pais,
            celular=phone.celular,
            motivo=motivo,
        )
        outcome["producto_match"] = _producto_brief(producto)
        return outcome

    # ── 4) Dedupe por email + CodigoLanzamiento ──────────────────────────────
    existing_opp = exists_oportunidad_activa(
        email=payload.correo,
        codigo_lanzamiento=producto["CodigoLanzamiento"],
    )
    if existing_opp:
        logger.info(
            "Duplicado: email=%s ya tiene opp activa Id=%s en CodigoLanzamiento=%s",
            payload.correo, existing_opp, producto["CodigoLanzamiento"],
        )
        return {
            "result":         "duplicate",
            "oportunidad_id": existing_opp,
            "message":        "Ya existe una oportunidad activa para este correo y producto.",
            "producto_match": _producto_brief(producto),
        }

    # ── 5) Pipeline transaccional ─────────────────────────────────────────────
    opp_input = OpportunityInput(
        nombres            = name_split.nombres,
        apellidos          = name_split.apellidos,
        email              = payload.correo,
        codigo_pais        = phone.codigo_pais,
        celular            = phone.celular,
        id_pais            = id_pais,
        producto_id        = int(producto["Id"]),
        codigo_lanzamiento = producto["CodigoLanzamiento"],
        costo_base         = float(producto["CostoBase"]) if producto.get("CostoBase") is not None else None,
        fecha_formulario   = payload.fecha_formulario,
    )

    with get_connection() as conn:
        result = create_opportunity(conn, opp_input)

    logger.info(
        "Oportunidad creada Id=%s persona=%s codigo_lanzamiento=%s auto_personal=%s",
        result.oportunidad_id, result.persona_id,
        producto["CodigoLanzamiento"], result.auto_assigned_personal_id,
    )
    return {
        "result":              "created",
        "oportunidad_id":      result.oportunidad_id,
        "persona_id":          result.persona_id,
        "codigo_lanzamiento":  producto["CodigoLanzamiento"],
        "auto_assigned_personal_id": result.auto_assigned_personal_id,
        "producto_match":      _producto_brief(producto),
    }


# ── Helpers: guardar en pendientes ────────────────────────────────────────────

def _save_as_pending_minimal(
    payload: WordpressLeadPayload,
    nombres: str,
    apellidos: str,
    motivo: str,
) -> dict[str, Any]:
    """Versión del guardado-en-pendientes cuando NO pudimos parsear el teléfono."""
    with get_connection() as conn:
        cur = conn.cursor()
        pid = insert_lead_pendiente(
            cur,
            nombre_capacitacion = payload.nombre_capacitacion,
            nombres             = nombres,
            apellidos           = apellidos,
            email               = payload.correo,
            telefono_raw        = payload.telefono,
            id_pais             = None,
            codigo_pais         = None,
            celular             = None,
            form_id             = payload.form_id,
            fecha_formulario    = payload.fecha_formulario,
            motivo              = motivo,
        )
    logger.info("Lead guardado en pendientes Id=%s motivo=%s", pid, motivo)
    return {"result": "pending", "pendiente_id": pid, "motivo": motivo}


def _save_as_pending_full(
    payload: WordpressLeadPayload,
    nombres: str,
    apellidos: str,
    id_pais: int | None,
    codigo_pais: str,
    celular: str,
    motivo: str,
) -> dict[str, Any]:
    """Versión con teléfono parseado (ej: sin match de producto)."""
    with get_connection() as conn:
        cur = conn.cursor()
        pid = insert_lead_pendiente(
            cur,
            nombre_capacitacion = payload.nombre_capacitacion,
            nombres             = nombres,
            apellidos           = apellidos,
            email               = payload.correo,
            telefono_raw        = payload.telefono,
            id_pais             = id_pais,
            codigo_pais         = codigo_pais,
            celular             = celular,
            form_id             = payload.form_id,
            fecha_formulario    = payload.fecha_formulario,
            motivo              = motivo,
        )
    logger.info("Lead guardado en pendientes Id=%s motivo=%s", pid, motivo)
    return {"result": "pending", "pendiente_id": pid, "motivo": motivo}
