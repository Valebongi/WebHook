"""FastAPI app para recibir leads del plugin de WordPress.

Correr con:
    uvicorn api:app --reload --port 8001
o:
    python start_server.py
"""

import logging
import secrets
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from config import CORS_ORIGINS, WORDPRESS_API_KEY
from models.wordpress_lead import WordpressLeadPayload
from services import request_log
from services.lead_service import process_wordpress_lead

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="WordPress Lead API",
    version="1.0.0",
    description="Recibe leads de formularios de WordPress y crea oportunidades.",
)

if CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ORIGINS,
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )


# ── Auth dependency ──────────────────────────────────────────────────────────

def require_api_key(x_api_key: str = Header(default="", alias="X-API-Key")) -> None:
    """Valida el header X-API-Key contra la clave configurada en .env."""
    if not WORDPRESS_API_KEY:
        logger.error("WORDPRESS_API_KEY no configurada — rechazando request")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key no configurada en el servidor.",
        )
    if not x_api_key or not secrets.compare_digest(x_api_key, WORDPRESS_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API key inválida o ausente.",
        )


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Healthcheck simple sin auth."""
    return {"status": "ok"}


@app.post(
    "/leads",
    dependencies=[Depends(require_api_key)],
    summary="Recibe un lead desde el form de WordPress y crea oportunidad.",
)
async def create_lead(request: Request):
    """Valida y procesa el payload. Registra TODO en el log en memoria."""
    # Leemos el body crudo primero para poder loggearlo aunque Pydantic rechace
    try:
        raw_body: dict[str, Any] = await request.json()
    except Exception as exc:
        request_log.record(
            payload_raw={"_error_parsing_json": str(exc)},
            http_status=400,
            result="invalid",
            message=f"JSON inválido: {exc}",
        )
        raise HTTPException(status_code=400, detail=f"JSON inválido: {exc}")

    # Validación Pydantic manual (para poder loggear el 422 con el payload original)
    try:
        payload = WordpressLeadPayload.model_validate(raw_body)
    except Exception as exc:
        errors = getattr(exc, "errors", lambda: [{"msg": str(exc)}])()
        request_log.record(
            payload_raw=raw_body,
            http_status=422,
            result="invalid",
            message="Payload inválido: " + "; ".join(
                f"{'.'.join(str(x) for x in e.get('loc', []))}: {e.get('msg', '')}"
                for e in errors
            ),
        )
        raise HTTPException(status_code=422, detail=errors)

    # Procesamiento del lead (errores no recuperables caen en except)
    try:
        outcome = process_wordpress_lead(payload)
    except Exception as exc:
        logger.exception("Error procesando lead de WP")
        request_log.record(
            payload_raw=raw_body,
            http_status=500,
            result="error",
            message=f"Error interno: {exc}",
        )
        raise HTTPException(
            status_code=500,
            detail=f"Error interno procesando el lead: {exc}",
        )

    # Dispatch por tipo de resultado
    if outcome["result"] == "created":
        request_log.record(
            payload_raw=raw_body,
            http_status=201,
            result="created",
            producto_match=outcome.get("producto_match"),
            oportunidad_id=outcome["oportunidad_id"],
            persona_id=outcome["persona_id"],
            message="Oportunidad creada",
        )
        return JSONResponse(
            status_code=201,
            content={
                "status":               "created",
                "oportunidad_id":       outcome["oportunidad_id"],
                "persona_id":           outcome["persona_id"],
                "codigo_lanzamiento":   outcome["codigo_lanzamiento"],
                "auto_assigned_personal_id": outcome.get("auto_assigned_personal_id"),
                "producto":             outcome.get("producto_match"),
                "message":              "Oportunidad creada correctamente.",
            },
        )
    if outcome["result"] == "pending":
        request_log.record(
            payload_raw=raw_body,
            http_status=202,
            result="pending",
            pendiente_id=outcome["pendiente_id"],
            producto_match=outcome.get("producto_match"),
            message=outcome["motivo"],
        )
        return JSONResponse(
            status_code=202,
            content={
                "status":       "pending",
                "pendiente_id": outcome["pendiente_id"],
                "motivo":       outcome["motivo"],
                "producto":     outcome.get("producto_match"),
                "message":      "Lead guardado en pendientes para revisión manual.",
            },
        )
    if outcome["result"] == "duplicate":
        request_log.record(
            payload_raw=raw_body,
            http_status=409,
            result="duplicate",
            producto_match=outcome.get("producto_match"),
            oportunidad_id=outcome["oportunidad_id"],
            message=outcome["message"],
        )
        return JSONResponse(
            status_code=409,
            content={
                "status":         "duplicate",
                "oportunidad_id": outcome["oportunidad_id"],
                "producto":       outcome.get("producto_match"),
                "message":        outcome["message"],
            },
        )
    raise HTTPException(status_code=500, detail=f"Resultado no reconocido: {outcome}")


# ── Observabilidad en localhost ──────────────────────────────────────────────

@app.get("/requests/recent", summary="Últimos requests recibidos (JSON).")
def get_recent_requests(limit: int = 50):
    """Log en memoria de los últimos requests. Se vacía al reiniciar el server."""
    return {"entries": request_log.recent(limit)}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def dashboard():
    """Página HTML simple con auto-refresh cada 3s sobre /requests/recent."""
    html_path = Path(__file__).parent / "static" / "dashboard.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))
