"""Configuración central del módulo WordPress-Lead-API.

Lee variables de entorno desde .env. Por defecto apunta a OlympusDB_QA
(ambiente de testeo). Para pasar a producción, cambiar DB_NAME a OlympusDB.
"""

import os
from dotenv import load_dotenv

load_dotenv()


def _get_int_env(name: str, default: int | None = None) -> int | None:
    """Lee un entero desde env; devuelve default si está vacío o es inválido."""
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        return default

# ── Database ──────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "server":   os.getenv("DB_SERVER",   "142.93.50.164"),
    "database": os.getenv("DB_NAME",     "OlympusDB_QA"),
    "username": os.getenv("DB_USER",     "GrowthArg"),
    "password": os.getenv("DB_PASSWORD", ""),
    "driver":   os.getenv("DB_DRIVER",   "ODBC Driver 17 for SQL Server"),
}

# Base de datos desde donde se LEE el catálogo de productos (`adm.Producto`).
# En testing conviene poner `OlympusDB` para trabajar contra el catálogo real
# sin tener que sincronizarlo en QA; las escrituras (Oportunidad, Persona, etc.)
# siguen yendo a DB_NAME. En producción, dejar igual a DB_NAME.
PRODUCTS_DB_NAME = os.getenv("PRODUCTS_DB_NAME", DB_CONFIG["database"])

# ── API auth ──────────────────────────────────────────────────────────────────
# Clave compartida con el plugin de WordPress. Si está vacía, la API arranca
# pero rechaza TODAS las requests: setearla siempre antes de ir a producción.
WORDPRESS_API_KEY = os.getenv("WORDPRESS_API_KEY", "")

# ── App ───────────────────────────────────────────────────────────────────────
API_PORT = int(os.getenv("PORT", os.getenv("API_PORT", "8001")))
API_HOST = os.getenv("API_HOST", "0.0.0.0")

# CORS: lista separada por comas. Vacío = no permitir nada por CORS
# (los requests directos del plugin de WP no necesitan CORS).
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]

# ── Constantes de negocio ─────────────────────────────────────────────────────
# Origen con el que se marca la Oportunidad creada.
OPORTUNIDAD_ORIGEN = "Wordpress"

# Usuario reportado en los campos de auditoría (UsuarioCreacion/Modificacion).
AUDIT_USER = "SYSTEM-WP"

# EstadoProductoTipoId permitidos (mismos que usa el SP de LinkedIn).
ESTADO_PRODUCTO_TIPOS_PERMITIDOS = (17, 19, 20)

# Estados de HistorialEstado que bloquean nueva oportunidad
# (1=Registrado, 3=Cobranza/Convertido, 4=Calificado, 5=Potencial, 6=Promesa).
ESTADOS_QUE_BLOQUEAN_NUEVA_OPP = (1, 3, 4, 5, 6)

# IdAsesor por defecto en el primer HistorialEstado (mismo valor que el SP).
DEFAULT_IDASESOR = 1
DEFAULT_IDESTADO_INICIAL = 1
DEFAULT_IDOCURRENCIA = 1

# adm.Moneda.Id = 4 corresponde a "Dólares Americanos / USD" (verificado en QA).
DEFAULT_ID_MONEDA_USD = 4

# ── Formulario WP 2 (sin producto en payload) ───────────────────────────────
# Usar un producto "comodín" activo en adm.Producto para crear oportunidades
# cuando el formulario no provee nombre/código de curso.
GENERIC_PRODUCTO_ID = _get_int_env("GENERIC_PRODUCTO_ID")
GENERIC_PRODUCTO_CODIGO_LANZAMIENTO = os.getenv(
    "GENERIC_PRODUCTO_CODIGO_LANZAMIENTO", "PROD-GENERICO-WP2"
)
GENERIC_PRODUCTO_NOMBRE = os.getenv(
    "GENERIC_PRODUCTO_NOMBRE", "GENERICO - Formulario WP 2"
)
