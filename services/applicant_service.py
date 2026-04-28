"""Servicio para guardar postulantes potenciales desde formulario web."""

from datetime import datetime

from config import AUDIT_USER
from db_connector import get_connection
from models.wordpress_applicant import WordpressApplicantPayload


def create_wordpress_applicant(
    payload: WordpressApplicantPayload,
    cv_nombre_archivo: str | None,
    cv_mime_type: str | None,
    cv_contenido: bytes | None,
) -> int:
    """Inserta una postulación potencial en adm.Wordpress_Postulante_Potencial."""
    now = datetime.now()

    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO adm.Wordpress_Postulante_Potencial
                (NombreCompleto, CorreoElectronico, AreaPostulacion,
                 CvNombreArchivo, CvMimeType, CvContenido, CvTamanoBytes,
                 Estado, FechaPostulacion,
                 FechaCreacion, UsuarioCreacion, FechaModificacion, UsuarioModificacion)
            OUTPUT inserted.Id
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            payload.nombre_completo[:255],
            str(payload.correo_electronico)[:255],
            payload.area_postulacion[:150],
            (cv_nombre_archivo or "")[:260] if cv_nombre_archivo else None,
            (cv_mime_type or "")[:100] if cv_mime_type else None,
            cv_contenido,
            len(cv_contenido) if cv_contenido else None,
            now,
            now,
            AUDIT_USER,
            now,
            AUDIT_USER,
        )
        row = cur.fetchone()
        return int(row[0])
