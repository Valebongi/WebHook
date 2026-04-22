"""Modelos Pydantic para el payload que envía el plugin de WordPress.

El formulario de WP manda los campos con nombres en español y con tildes.
Para facilitar la integración aceptamos varios alias (via Field(alias=...)).
"""

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


class WordpressLeadPayload(BaseModel):
    """Payload que llega desde el formulario de WordPress.

    Acepta múltiples aliases por campo para tolerar los nombres que envía
    WPForms directamente (donde `$field['name']` es el label del campo y
    puede venir con espacios, tildes o mayúsculas).

    Nombres aceptados por campo:
      - nombre_capacitacion / nombreCapacitacion / curso / nombre_curso
      - nombres_apellidos / "Nombres y apellidos" / nombre_completo /
        nombreCompleto / nombres
      - telefono / "Teléfono" / "Telefono" / phone
      - correo / email / "Correo electrónico" / "Correo electronico"
      - form_id / formId
      - entry_id / entryId (opcional, ignorado a nivel de negocio)
      - fecha_formulario / fechaFormulario (opcional)
    """

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    nombre_capacitacion: str = Field(
        ..., min_length=1, max_length=300,
        validation_alias=AliasChoices(
            "nombre_capacitacion", "nombreCapacitacion", "curso", "nombre_curso",
        ),
    )
    nombres_apellidos: str = Field(
        ..., min_length=1, max_length=300,
        validation_alias=AliasChoices(
            "nombres_apellidos", "nombresApellidos", "nombre_completo",
            "nombreCompleto", "nombres", "Nombres y apellidos",
        ),
    )
    telefono: str = Field(
        ..., min_length=4, max_length=40,
        validation_alias=AliasChoices(
            "telefono", "Teléfono", "Telefono", "phone", "celular",
        ),
    )
    correo: EmailStr = Field(
        ...,
        validation_alias=AliasChoices(
            "correo", "email", "Correo electrónico", "Correo electronico",
        ),
    )
    form_id: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("form_id", "formId"),
    )
    entry_id: Optional[int] = Field(
        default=None,
        validation_alias=AliasChoices("entry_id", "entryId"),
    )
    fecha_formulario: Optional[datetime] = Field(
        default=None,
        validation_alias=AliasChoices("fecha_formulario", "fechaFormulario"),
    )

    @field_validator("nombre_capacitacion", "nombres_apellidos")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("campo vacío")
        return v.strip()


class LeadCreatedResponse(BaseModel):
    status:         str
    oportunidad_id: int
    persona_id:     int
    codigo_lanzamiento: str
    message:        str


class LeadPendingResponse(BaseModel):
    status:   str
    pendiente_id: int
    motivo:   str
    message:  str


class LeadDuplicateResponse(BaseModel):
    status:  str
    oportunidad_id: Optional[int] = None
    message: str
