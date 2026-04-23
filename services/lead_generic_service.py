"""Orquestador del endpoint POST /leads-generic.

Procesa leads de formularios WP que no traen producto estandarizado.
Usa un producto genérico configurado en entorno y ejecuta el mismo pipeline
transaccional de creación de oportunidad.
"""

import logging
from typing import Any

from config import (
    GENERIC_PRODUCTO_CODIGO_LANZAMIENTO,
    GENERIC_PRODUCTO_ID,
    GENERIC_PRODUCTO_NOMBRE,
)
from db_connector import (
    exists_oportunidad_activa,
    fetch_pais_por_prefijo,
    fetch_producto_generico,
    get_connection,
)
from models.wordpress_lead_generic import WordpressLeadGenericPayload
from services.opportunity_builder import OpportunityInput, create_opportunity, insert_lead_pendiente
from validators.form_validator import parse_phone, split_full_name

logger = logging.getLogger(__name__)


def _producto_brief(producto: dict) -> dict:
    return {
        "Id": int(producto["Id"]),
        "Nombre": producto["Nombre"],
        "CodigoLanzamiento": producto.get("CodigoLanzamiento"),
        "CodigoLinkedin": producto.get("CodigoLinkedin"),
        "CostoBase": float(producto["CostoBase"]) if producto.get("CostoBase") is not None else None,
    }


def process_wordpress_generic_lead(payload: WordpressLeadGenericPayload) -> dict[str, Any]:
    """Procesa un lead del segundo formulario de WordPress."""
    name_split = split_full_name(payload.nombres_apellidos)
    phone = parse_phone(payload.telefono)

    if phone is None:
        return _save_as_pending_generic(
            payload=payload,
            nombres=name_split.nombres,
            apellidos=name_split.apellidos,
            id_pais=None,
            codigo_pais=None,
            celular=None,
            motivo="Teléfono no parseable con phonenumbers (formulario genérico)",
        )

    prefijo_num = int(phone.codigo_pais.lstrip("+"))
    pais_row = fetch_pais_por_prefijo(prefijo_num)
    id_pais = int(pais_row["Id"]) if pais_row else None

    producto = fetch_producto_generico(
        producto_id=GENERIC_PRODUCTO_ID,
        codigo_lanzamiento=GENERIC_PRODUCTO_CODIGO_LANZAMIENTO,
    )
    if not producto:
        raise RuntimeError(
            "Producto genérico no configurado/activo en adm.Producto. "
            f"Revisar GENERIC_PRODUCTO_ID={GENERIC_PRODUCTO_ID} o "
            f"GENERIC_PRODUCTO_CODIGO_LANZAMIENTO='{GENERIC_PRODUCTO_CODIGO_LANZAMIENTO}'."
        )

    existing_opp = exists_oportunidad_activa(
        email=payload.correo,
        codigo_lanzamiento=producto["CodigoLanzamiento"],
    )
    if existing_opp:
        return {
            "result": "duplicate",
            "oportunidad_id": existing_opp,
            "message": "Ya existe una oportunidad activa para este correo y producto.",
            "producto_match": _producto_brief(producto),
        }

    opp_input = OpportunityInput(
        nombres=name_split.nombres,
        apellidos=name_split.apellidos,
        email=payload.correo,
        codigo_pais=phone.codigo_pais,
        celular=phone.celular,
        id_pais=id_pais,
        producto_id=int(producto["Id"]),
        codigo_lanzamiento=producto["CodigoLanzamiento"],
        costo_base=float(producto["CostoBase"]) if producto.get("CostoBase") is not None else None,
        fecha_formulario=payload.fecha_formulario,
    )

    with get_connection() as conn:
        result = create_opportunity(conn, opp_input)

    return {
        "result": "created",
        "oportunidad_id": result.oportunidad_id,
        "persona_id": result.persona_id,
        "codigo_lanzamiento": producto["CodigoLanzamiento"],
        "auto_assigned_personal_id": result.auto_assigned_personal_id,
        "producto_match": _producto_brief(producto),
    }


def _save_as_pending_generic(
    payload: WordpressLeadGenericPayload,
    nombres: str,
    apellidos: str,
    id_pais: int | None,
    codigo_pais: str | None,
    celular: str | None,
    motivo: str,
) -> dict[str, Any]:
    """Guarda lead genérico en pendientes cuando no se puede crear opp."""
    consulta = (payload.consulta or "").strip()
    motivo_full = motivo
    if consulta:
        motivo_full = (motivo + " | Consulta: " + consulta[:200])[:300]

    with get_connection() as conn:
        cur = conn.cursor()
        pid = insert_lead_pendiente(
            cur,
            nombre_capacitacion=GENERIC_PRODUCTO_NOMBRE,
            nombres=nombres,
            apellidos=apellidos,
            email=payload.correo,
            telefono_raw=payload.telefono,
            id_pais=id_pais,
            codigo_pais=codigo_pais,
            celular=celular,
            form_id=payload.form_id,
            fecha_formulario=payload.fecha_formulario,
            motivo=motivo_full,
        )

    logger.info("Lead genérico guardado en pendientes Id=%s motivo=%s", pid, motivo_full)
    return {"result": "pending", "pendiente_id": pid, "motivo": motivo_full}
