"""Ring buffer en memoria de los últimos requests a /leads.

Pensado para **observación durante testing**. No persiste: si el server se
reinicia, se pierde. Para producción, reemplazar por tabla en BD.
"""

import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any, Optional

_MAX_ENTRIES = 100
_entries: deque[dict] = deque(maxlen=_MAX_ENTRIES)
_lock = threading.Lock()


def record(
    *,
    payload_raw: Any,
    http_status: int,
    result: str,                # "created" | "pending" | "duplicate" | "invalid" | "error"
    producto_match: Optional[dict] = None,   # {Id, Nombre, CodigoLanzamiento} o None
    oportunidad_id: Optional[int] = None,
    persona_id: Optional[int] = None,
    pendiente_id: Optional[int] = None,
    message: Optional[str] = None,
) -> None:
    """Registra un request. Se llama desde el endpoint después de procesar."""
    entry = {
        "timestamp":       datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "http_status":     http_status,
        "result":          result,
        "payload":         _sanitize_payload(payload_raw),
        "producto_match":  producto_match,
        "oportunidad_id":  oportunidad_id,
        "persona_id":      persona_id,
        "pendiente_id":    pendiente_id,
        "message":         message,
    }
    with _lock:
        _entries.appendleft(entry)


def recent(limit: int = 50) -> list[dict]:
    """Devuelve los últimos `limit` entries, del más reciente al más viejo."""
    with _lock:
        return list(_entries)[:limit]


def _sanitize_payload(payload: Any) -> Any:
    """Convierte el payload a algo serializable a JSON.

    - Si es dict, lo convertimos a strings seguros (truncados a 500 chars).
    - Si es Pydantic BaseModel, usamos model_dump(by_alias=False).
    """
    if payload is None:
        return None
    # Pydantic BaseModel
    dump = getattr(payload, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:
            pass
    if isinstance(payload, dict):
        return {str(k): _trim(v) for k, v in payload.items()}
    return _trim(payload)


def _trim(v: Any) -> Any:
    if isinstance(v, str) and len(v) > 500:
        return v[:500] + "...(truncated)"
    return v
