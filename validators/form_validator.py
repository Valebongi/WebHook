"""Validaciones del payload del form de WordPress.

Incluye:
  - Parseo / normalización del teléfono vía `phonenumbers`.
  - Inferencia de país a partir del prefijo del teléfono.
  - Split de "Nombres y apellidos" en Nombre + Apellidos.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import phonenumbers
from phonenumbers import (
    NumberParseException,
    PhoneNumberFormat,
    format_number,
    is_valid_number,
    region_code_for_number,
)

logger = logging.getLogger(__name__)

_JUNK_RE = re.compile(r"[^0-9+\-\s]")


@dataclass
class PhoneInfo:
    """Resultado de normalizar un teléfono recibido del form."""
    codigo_pais:   str          # "+57"
    celular:       str          # "310 456 7890" (international sin prefijo)
    iso2:          str          # "CO"
    celular_full:  str          # "+57 310 456 7890" (para logging)
    raw:           str          # valor original


@dataclass
class NameSplit:
    nombres:   str
    apellidos: str


def clean_phone_raw(raw: str) -> str:
    """Quita caracteres basura (backticks, letras, etc.) de un teléfono."""
    cleaned = _JUNK_RE.sub("", raw or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def parse_phone(raw: str) -> Optional[PhoneInfo]:
    """Intenta parsear un teléfono y devolver (prefijo, celular, ISO-2).

    Estrategia:
      1. Parseo directo (requiere formato internacional con `+`).
      2. Si falta el `+` al principio, prepender y reintentar.
      3. Devuelve None si no se pudo validar.
    """
    if not raw:
        return None

    cleaned = clean_phone_raw(raw)
    attempts = [cleaned]
    if not cleaned.startswith("+"):
        attempts.append("+" + cleaned)

    for attempt in attempts:
        try:
            num = phonenumbers.parse(attempt, None)
            if is_valid_number(num):
                cc = num.country_code
                intl = format_number(num, PhoneNumberFormat.INTERNATIONAL)
                prefix = f"+{cc} "
                celular_local = intl[len(prefix):] if intl.startswith(prefix) else intl
                iso2 = region_code_for_number(num) or ""
                return PhoneInfo(
                    codigo_pais  = f"+{cc}",
                    celular      = celular_local,
                    iso2         = iso2,
                    celular_full = intl,
                    raw          = raw,
                )
        except NumberParseException:
            continue

    return None


def split_full_name(full_name: str) -> NameSplit:
    """Divide "Nombres y apellidos" en dos partes.

    Heurística simple: la primera palabra es el nombre, el resto son apellidos.
    Ejemplos:
      "Sandro Che Vallejos" → Nombres="Sandro", Apellidos="Che Vallejos"
      "Ana María Pérez"     → Nombres="Ana",    Apellidos="María Pérez"
      "Juan"                → Nombres="Juan",   Apellidos=""

    Se mantiene intencionalmente simple: si el cliente quiere dos nombres
    (p.ej. "Ana María"), el primer nombre queda como Nombres y el resto se
    considera Apellidos. Es correcto en la mayoría de los casos y no vale la
    pena hacer algo más sofisticado a este nivel.
    """
    words = (full_name or "").strip().split()
    if not words:
        return NameSplit(nombres="", apellidos="")
    if len(words) == 1:
        return NameSplit(nombres=words[0], apellidos="")
    return NameSplit(nombres=words[0], apellidos=" ".join(words[1:]))
