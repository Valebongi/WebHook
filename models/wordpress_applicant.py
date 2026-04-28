"""Modelos Pydantic para postulaciones potenciales desde formulario web."""

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


class WordpressApplicantPayload(BaseModel):
    """Payload esperado para guardar postulantes potenciales.

    Campos aceptados:
      - nombre_completo / nombreCompleto / nombres
      - correo_electronico / correoElectronico / email
      - area_postulacion / areaPostulacion / area
    """

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    nombre_completo: str = Field(
        ..., min_length=1, max_length=255,
        validation_alias=AliasChoices("nombre_completo", "nombreCompleto", "nombres"),
    )
    correo_electronico: EmailStr = Field(
        ...,
        validation_alias=AliasChoices("correo_electronico", "correoElectronico", "email", "correo"),
    )
    area_postulacion: str = Field(
        ..., min_length=1, max_length=150,
        validation_alias=AliasChoices("area_postulacion", "areaPostulacion", "area"),
    )

    @field_validator("nombre_completo", "area_postulacion")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("campo vacío")
        return v.strip()
