"""Cliente HTTP del servicio externo de reconstruccion AXON (modo de una radiografia).

El servicio corre fuera del sistema, en una GPU de Colab expuesta con ngrok, y lo
enciende Lourdes cuando hace falta. Para este cliente es solo una direccion web con
una clave: se le envia un DICOM y devuelve un volumen .nii.gz. El contrato esta en la
seccion 4 de la guia del modo de una radiografia:

- GET  /health                  sin clave. {"estado": "ok", ...}
- POST /jobs                    multipart: file (el archivo) y formato=normal.
                                {"job_id": "...", "en_cola": n}
- GET  /jobs/{job_id}           {"estado": "queued|running|done|error", "error": ...}
- GET  /jobs/{job_id}/resultado el .nii.gz; solo cuando el estado es done.

Todas las llamadas llevan ngrok-skip-browser-warning: 1, y las que piden clave,
X-API-Key. Si el tunel esta apagado, ngrok responde una pagina HTML (ERR_NGROK_3200,
codigo 404): por eso una respuesta que no es JSON cuenta como servicio no disponible y
nunca se intenta leer como JSON.

Esta en la persistencia porque es acceso a un servicio externo, como el bucket. Usa
solo la biblioteca estandar (urllib): no agrega dependencias al proyecto.

La clave nunca sale de aqui: no se registra, no va en ningun mensaje de error y no se
copia a ningun objeto que se pueda mostrar. Los mensajes tampoco llevan la direccion.
"""

import json
import logging
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest

from pydantic import SecretStr

from radvol3d.domain.exceptions import (
    ReconstructionServiceUnavailableError,
    RemoteReconstructionError,
)
from radvol3d.persistence.settings import ReconstructionServiceSettings

logger = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "El modo de una radiografía no está disponible en este momento."

# Un job_id del servicio: hexadecimal corto ("636f7969d6e7"). Se valida antes de
# ponerlo en una ruta, para que una respuesta rara no pueda armar otra direccion.
JOB_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")

# Estados que devuelve el servicio.
QUEUED, RUNNING, DONE, ERROR = "queued", "running", "done", "error"
KNOWN_STATES = frozenset({QUEUED, RUNNING, DONE, ERROR})

# Tope de lo que se lee de cada respuesta: un volumen pesa de 4 a 7 MB y un JSON,
# unos cientos de bytes. Un tope evita llenar la memoria con una respuesta absurda.
MAX_RESULT_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 64 * 1024

_COMMON_HEADERS = {
    "ngrok-skip-browser-warning": "1",
    "User-Agent": "RadVol3D",
    "Accept": "application/json",
}

# Abre una peticion con un tiempo de espera; en las pruebas se puede sustituir.
Opener = Callable[[urlrequest.Request, float], Any]


def _default_opener(request: urlrequest.Request, timeout: float) -> Any:
    return urlrequest.urlopen(request, timeout=timeout)  # noqa: S310 - https de la config


@dataclass(frozen=True)
class RemoteJobStatus:
    """Estado de un trabajo en el servicio."""

    state: str
    seconds: float | None = None
    error: str | None = None
    queue_position: int | None = None


@dataclass(frozen=True)
class _Response:
    status: int
    content_type: str
    body: bytes


class ReconstructionServiceClient:
    """Implementa el contrato del servicio AXON con tiempos de espera acotados."""

    def __init__(
        self,
        base_url: str,
        api_key: SecretStr | str,
        *,
        health_timeout: float = 5.0,
        upload_timeout: float = 120.0,
        request_timeout: float = 30.0,
        opener: Opener | None = None,
    ) -> None:
        if not base_url or not str(base_url).strip():
            raise ValueError("Falta la direccion del servicio de reconstruccion.")
        self._base_url = str(base_url).strip().rstrip("/")
        self._api_key = api_key if isinstance(api_key, SecretStr) else SecretStr(api_key)
        self._health_timeout = health_timeout
        self._upload_timeout = upload_timeout
        self._request_timeout = request_timeout
        self._open = opener or _default_opener

    @classmethod
    def from_settings(
        cls, settings: ReconstructionServiceSettings
    ) -> "ReconstructionServiceClient | None":
        """El cliente configurado, o None si falta AXON_URL o AXON_API_KEY."""
        if not settings.configured:
            return None
        return cls(
            settings.axon_url or "",
            settings.axon_api_key or "",
            health_timeout=settings.axon_health_timeout_seconds,
            upload_timeout=settings.axon_upload_timeout_seconds,
            request_timeout=settings.axon_request_timeout_seconds,
        )

    def __repr__(self) -> str:
        # Ni la direccion ni la clave: un repr puede terminar en un registro.
        return "ReconstructionServiceClient()"

    # ------------------------------------------------------------------ contrato

    def is_alive(self) -> bool:
        """True si /health responde {"estado": "ok"} dentro del tiempo corto. Nunca lanza."""
        try:
            response = self._send("GET", "/health", timeout=self._health_timeout, with_key=False)
            body = self._json(response)
        except (ReconstructionServiceUnavailableError, RemoteReconstructionError):
            return False
        return response.status == 200 and body.get("estado") == "ok"

    def submit(self, data: bytes, filename: str = "radiograph.dcm") -> str:
        """Envia la radiografia y devuelve el job_id del trabajo creado."""
        boundary = uuid.uuid4().hex
        body = _multipart(
            boundary,
            fields={"formato": "normal"},
            files={"file": (filename, data, "application/dicom")},
        )
        response = self._send(
            "POST",
            "/jobs",
            timeout=self._upload_timeout,
            body=body,
            content_type=f"multipart/form-data; boundary={boundary}",
        )
        self._raise_for_status(response, "enviar la radiografia")
        job_id = self._json(response).get("job_id")
        if not isinstance(job_id, str) or JOB_ID_PATTERN.fullmatch(job_id) is None:
            raise RemoteReconstructionError(
                "El servicio de reconstruccion no devolvio un identificador de trabajo valido."
            )
        return job_id

    def status(self, job_id: str) -> RemoteJobStatus:
        """Estado del trabajo. Un 404 (trabajo perdido) lanza RemoteReconstructionError."""
        response = self._send("GET", f"/jobs/{_checked(job_id)}", timeout=self._request_timeout)
        self._raise_for_status(response, "consultar el trabajo")
        body = self._json(response)
        state = body.get("estado")
        if state not in KNOWN_STATES:
            raise RemoteReconstructionError(
                "El servicio de reconstruccion devolvio un estado desconocido."
            )
        seconds = body.get("segundos")
        position = body.get("en_cola")
        return RemoteJobStatus(
            state=state,
            seconds=float(seconds) if isinstance(seconds, int | float) else None,
            error=str(body["error"])[:300] if body.get("error") else None,
            queue_position=position if isinstance(position, int) else None,
        )

    def download(self, job_id: str) -> bytes:
        """Descarga el volumen (.nii.gz) de un trabajo terminado."""
        response = self._send(
            "GET",
            f"/jobs/{_checked(job_id)}/resultado",
            timeout=self._upload_timeout,
            accept="application/gzip, application/octet-stream",
            limit=MAX_RESULT_BYTES,
        )
        self._raise_for_status(response, "descargar el volumen")
        if _is_html(response):
            raise ReconstructionServiceUnavailableError(UNAVAILABLE_MESSAGE)
        if not response.body:
            raise RemoteReconstructionError(
                "El servicio de reconstruccion devolvio un volumen vacio."
            )
        return response.body

    # ------------------------------------------------------------------ HTTP

    def _send(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        body: bytes | None = None,
        content_type: str | None = None,
        with_key: bool = True,
        accept: str | None = None,
        limit: int = MAX_JSON_BYTES,
    ) -> _Response:
        headers = dict(_COMMON_HEADERS)
        if accept:
            headers["Accept"] = accept
        if content_type:
            headers["Content-Type"] = content_type
        if with_key:
            headers["X-API-Key"] = self._api_key.get_secret_value()
        request = urlrequest.Request(
            self._base_url + path, data=body, headers=headers, method=method
        )
        try:
            with self._open(request, timeout) as raw:
                return _Response(
                    status=getattr(raw, "status", 200),
                    content_type=raw.headers.get("Content-Type", "") or "",
                    body=_read_limited(raw, limit),
                )
        except urlerror.HTTPError as http_error:
            # Un codigo 4xx o 5xx: el cuerpo dice si es del servicio (JSON) o de ngrok.
            try:
                content = _read_limited(http_error, MAX_JSON_BYTES)
            except Exception:  # noqa: BLE001 - el cuerpo es solo informativo
                content = b""
            content_type = http_error.headers.get("Content-Type", "") if http_error.headers else ""
            return _Response(status=http_error.code, content_type=content_type or "", body=content)
        except (urlerror.URLError, TimeoutError, ConnectionError, OSError) as cause:
            # Sin respuesta: tunel cerrado, Colab apagado, DNS o tiempo agotado. Solo el
            # tipo va al registro; el texto podria traer la direccion.
            logger.warning("El servicio de reconstruccion no respondio (%s)", type(cause).__name__)
            raise ReconstructionServiceUnavailableError(UNAVAILABLE_MESSAGE) from None

    @staticmethod
    def _json(response: _Response) -> dict[str, Any]:
        """El cuerpo como objeto JSON. HTML (pagina de ngrok) cuenta como no disponible."""
        if _is_html(response) or "json" not in response.content_type.lower():
            raise ReconstructionServiceUnavailableError(UNAVAILABLE_MESSAGE)
        try:
            body = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise RemoteReconstructionError(
                "El servicio de reconstruccion devolvio una respuesta que no se entiende."
            ) from None
        if not isinstance(body, dict):
            raise RemoteReconstructionError(
                "El servicio de reconstruccion devolvio una respuesta que no se entiende."
            )
        return body

    @staticmethod
    def _raise_for_status(response: _Response, action: str) -> None:
        """Traduce los codigos de la seccion 4.3 de la guia."""
        code = response.status
        if 200 <= code < 300:
            return
        if _is_html(response) or code in (502, 503, 504):
            # ERR_NGROK_3200 (tunel cerrado) o un proxy sin servicio detras.
            raise ReconstructionServiceUnavailableError(UNAVAILABLE_MESSAGE)
        if code == 401:
            # Error de configuracion: no se reintenta y no se dan detalles al usuario.
            logger.error("El servicio de reconstruccion rechazo la clave (401).")
            raise RemoteReconstructionError(
                "El servicio de reconstruccion rechazo la configuracion del servidor."
            )
        if code == 404:
            raise RemoteReconstructionError(
                "El trabajo ya no existe en el servicio de reconstruccion (por ejemplo, se "
                "reinicio). Vuelve a intentarlo."
            )
        if code == 409:
            raise RemoteReconstructionError("El trabajo todavia no termina.")
        if code == 413:
            raise RemoteReconstructionError(
                "La radiografia supera el tamano que admite el servicio de reconstruccion."
            )
        if code == 400:
            raise RemoteReconstructionError(
                "El servicio de reconstruccion no acepto el archivo enviado."
            )
        raise RemoteReconstructionError(
            f"El servicio de reconstruccion fallo al {action} (codigo {code})."
        )


def _checked(job_id: str) -> str:
    if not isinstance(job_id, str) or JOB_ID_PATTERN.fullmatch(job_id) is None:
        raise RemoteReconstructionError("Identificador de trabajo invalido.")
    return job_id


def _is_html(response: _Response) -> bool:
    if "html" in response.content_type.lower():
        return True
    start = response.body[:200].lstrip().lower()
    return (
        start.startswith(b"<!doctype html")
        or start.startswith(b"<html")
        or (b"err_ngrok" in response.body[:4096].lower())
    )


def _read_limited(raw: Any, limit: int) -> bytes:
    """Lee hasta limit bytes. Si la respuesta es mas grande, falla en vez de truncarla."""
    content = raw.read(limit + 1)
    if len(content) > limit:
        raise RemoteReconstructionError(
            "La respuesta del servicio de reconstruccion es demasiado grande."
        )
    return content


def _multipart(
    boundary: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> bytes:
    """Arma un cuerpo multipart/form-data a mano (urllib no lo hace)."""
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            + value.encode()
            + b"\r\n"
        )
    for name, (filename, data, mime) in files.items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n\r\n"
            ).encode()
            + data
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts)
