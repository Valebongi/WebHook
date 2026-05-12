"""Reprocesa los leads bloqueados en adm.Wordpress_Lead_Pendiente (Estado=0).

Estrategia:
  - Por cada pendiente con CodigoPais+Celular (teléfono parseado), intenta crear
    la oportunidad con el producto genérico configurado en .env.
  - Los pendientes sin teléfono no pueden crearse como oportunidad (se saltan).
  - Dedupe: si ya existe una opp activa para ese email+CodigoLanzamiento, marca
    el pendiente como procesado con motivo "Duplicado".
  - Al finalizar, actualiza Estado=1 en cada pendiente procesado.

Uso:
    cd WebHook
    python reprocesar_pendientes.py [--dry-run]
"""

import argparse
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def main(dry_run: bool) -> None:
    import pyodbc
    from config import (
        GENERIC_PRODUCTO_CODIGO_LANZAMIENTO,
        GENERIC_PRODUCTO_ID,
    )
    from db_connector import (
        exists_oportunidad_activa,
        fetch_producto_generico,
        get_connection,
    )
    from services.opportunity_builder import OpportunityInput, create_opportunity

    producto = fetch_producto_generico(
        producto_id=GENERIC_PRODUCTO_ID,
        codigo_lanzamiento=GENERIC_PRODUCTO_CODIGO_LANZAMIENTO,
    )
    if producto is None:
        logger.error(
            "Producto genérico no encontrado (id=%s, cl=%s). "
            "Verificar GENERIC_PRODUCTO_ID en .env.",
            GENERIC_PRODUCTO_ID, GENERIC_PRODUCTO_CODIGO_LANZAMIENTO,
        )
        sys.exit(1)

    logger.info(
        "Producto genérico: id=%s nombre='%s' cl=%s",
        producto["Id"], producto["Nombre"], producto["CodigoLanzamiento"],
    )

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT Id, NombreCapacitacion, Nombres, Apellidos, Email,
                   Telefono, IdPais, CodigoPais, Celular, FormId, FechaFormulario,
                   MotivoPendiente
            FROM adm.Wordpress_Lead_Pendiente
            WHERE Estado = 0
            ORDER BY Id
            """
        )
        pendientes = cur.fetchall()
        cols = [c[0] for c in cur.description]

    rows = [dict(zip(cols, r)) for r in pendientes]
    logger.info("Total pendientes Estado=0: %d", len(rows))
    if not rows:
        logger.info("Nada que reprocesar.")
        return

    total_creadas = 0
    total_duplicadas = 0
    total_saltadas = 0
    total_errores = 0

    for row in rows:
        pid = row["Id"]
        email = (row["Email"] or "").strip()
        codigo_pais = row["CodigoPais"]
        celular = row["Celular"]

        if not codigo_pais or not celular:
            logger.info(
                "[%d] Saltado — sin teléfono parseado (CodigoPais=%s Celular=%s)",
                pid, codigo_pais, celular,
            )
            total_saltadas += 1
            continue

        try:
            existing = exists_oportunidad_activa(
                email=email,
                codigo_lanzamiento=producto["CodigoLanzamiento"],
            )
            if existing:
                logger.info(
                    "[%d] Duplicado — email=%s ya tiene opp activa Id=%s",
                    pid, email, existing,
                )
                if not dry_run:
                    _marcar_procesado(pid, f"Duplicado: oportunidad existente Id={existing}")
                total_duplicadas += 1
                continue

            opp_input = OpportunityInput(
                nombres=row["Nombres"] or "",
                apellidos=row["Apellidos"] or "",
                email=email,
                codigo_pais=codigo_pais,
                celular=celular,
                id_pais=int(row["IdPais"]) if row["IdPais"] is not None else None,
                producto_id=int(producto["Id"]),
                codigo_lanzamiento=producto["CodigoLanzamiento"],
                costo_base=None,
                fecha_formulario=row["FechaFormulario"],
            )

            if dry_run:
                logger.info(
                    "[%d] [DRY-RUN] Crearía opp para email=%s producto_id=%s",
                    pid, email, producto["Id"],
                )
                total_creadas += 1
                continue

            with get_connection() as conn2:
                result = create_opportunity(conn2, opp_input)

            _marcar_procesado(pid, f"Oportunidad creada Id={result.oportunidad_id}")
            logger.info(
                "[%d] Oportunidad creada Id=%s persona=%s",
                pid, result.oportunidad_id, result.persona_id,
            )
            total_creadas += 1

        except Exception as exc:
            logger.error("[%d] Error: %s", pid, exc)
            total_errores += 1

    logger.info(
        "Resultado%s — creadas: %d | duplicadas: %d | saltadas: %d | errores: %d",
        " (DRY-RUN)" if dry_run else "",
        total_creadas, total_duplicadas, total_saltadas, total_errores,
    )


def _marcar_procesado(pendiente_id: int, motivo_resolucion: str) -> None:
    from datetime import datetime
    from config import AUDIT_USER
    from db_connector import get_connection

    with get_connection() as conn:
        conn.cursor().execute(
            """
            UPDATE adm.Wordpress_Lead_Pendiente
            SET Estado = 1,
                MotivoPendiente = SUBSTRING(
                    ISNULL(MotivoPendiente, '') + ' | RESUELTO: ' + ?,
                    1, 300
                ),
                FechaModificacion = ?,
                UsuarioModificacion = ?
            WHERE Id = ?
            """,
            motivo_resolucion, datetime.now(), AUDIT_USER, pendiente_id,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reprocesar Wordpress_Lead_Pendiente")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Solo muestra qué haría, sin escribir en la BD.",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
