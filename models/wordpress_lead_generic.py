"""Modelo Pydantic para el segundo formulario de WordPress (sin producto)."""

from datetime import datetime
from typing import Optional

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


class WordpressLeadGenericPayload(BaseModel):
    """Payload del formulario que solo trae datos de contacto y consulta."""

    model_config = ConfigDict(populate_by_name=True, str_strip_whitespace=True)

    nombres_apellidos: str = Field(
        ..., min_length=1, max_length=300,
        validation_alias=AliasChoices(
            "nombres_apellidos",
            "nombresApellidos",
            "nombre_completo",
            "nombreCompleto",
            "nombres",
            "Nombres y apellidos",
            "Nombres",
            "Nombre",
        ),
    )
    telefono: str = Field(
        ..., min_length=4, max_length=40,
        validation_alias=AliasChoices(
            "telefono",
            "Teléfono",
            "Telefono",
            "phone",
            "celular",
            "Celular",
        ),
    )
    correo: EmailStr = Field(
        ...,
        validation_alias=AliasChoices(
            "correo",
            "email",
            "Correo electrónico",
            "Correo electronico",
            "Correo",
        ),
    )
    consulta: Optional[str] = Field(
        default=None,
        max_length=3000,
        validation_alias=AliasChoices(
            "consulta",
            "Consulta",
            "descripcion_consulta",
            "descripcionConsulta",
            "mensaje",
            "Mensaje",
            "comments",
            "Comentarios",
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

    @field_validator("nombres_apellidos")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("campo vacío")
        return v.strip()
