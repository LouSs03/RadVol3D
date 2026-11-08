#!/usr/bin/env python3
"""Servicio simulado de AXON: imita el contrato de la seccion 4 de la guia.

Sirve para desarrollar y probar el modo de una radiografia sin GPU, sin Colab, sin
ngrok y sin la clave real (seccion 6.2 de la guia). Solo usa la biblioteca estandar.

Mismos cuatro puntos de acceso, mismos estados y mismos codigos que el real:

- GET  /health                  {"estado": "ok", "gpu": "simulada", ...}
- POST /jobs                    multipart (file, formato=normal) -> {"job_id", "en_cola"}
- GET  /jobs/{job_id}           {"job_id", "estado", "segundos", "error"}
- GET  /jobs/{job_id}/resultado el .nii.gz (uno de los volumenes de ejemplo)

Pide la cabecera X-API-Key en todo menos /health (401 si falta o no coincide), rechaza
formatos y extensiones raras (400) y archivos de mas de 60 MB (413).

Modo (variable AXON_MOCK_MODE o --mode):

- ok:      el trabajo pasa a running y despues a done.
- apagado: todo responde la pagina HTML de ngrok con ERR_NGROK_3200 y codigo 404,
           como cuando el tunel esta cerrado.
- error:   el trabajo termina en error.
- lento:   como ok, pero cada paso tarda --slow-seconds (por omision 300 s).
- perdido: el trabajo se crea, pero al consultarlo responde 404 (Colab se reinicio).

Uso, en una terminal aparte:

    python scripts/axon_mock_server.py --volumes ~/volumenes_ejemplo --key clave-de-prueba

y en el .env del backend:

    AXON_URL=http://127.0.0.1:8765
    AXON_API_KEY=clave-de-prueba
    AXON_POLL_SECONDS=1

Para cambiar de modo sin reiniciar: POST /mock/mode con el cuerpo {"mode": "apagado"}.
Si --volumes no tiene archivos .nii.gz, devuelve un volumen sintetico de 128^3.
"""

import argparse
import gzip
import itertools
import json
import os
import random
import re
import struct
import sys
import threading
import time
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

MODES = ("ok", "apagado", "error", "lento", "perdido")
MAX_UPLOAD_BYTES = 60 * 1024 * 1024
ACCEPTED_EXTENSIONS = {"", ".dcm", ".dicom", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
NGROK_OFFLINE_PAGE = (
    b"<!DOCTYPE html><html><head><title>ngrok</title></head><body>"
    b"<p>The endpoint is offline.</p><p>ERR_NGROK_3200</p></body></html>"
)


class MockState:
    """Trabajos en memoria y el modo actual. Un trabajo a la vez, como la GPU real."""

    def __init__(
        self, mode: str, api_key: str, step_seconds: float, slow_seconds: float, volumes: list[Path]
    ) -> None:
        self.mode = mode
        self.api_key = api_key
        self.step_seconds = step_seconds
        self.slow_seconds = slow_seconds
        self.volumes = volumes
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()
        self._counter = itertools.count(1)

    def new_job(self) -> tuple[str, int]:
        with self.lock:
            job_id = f"{next(self._counter):04d}{random.getrandbits(32):08x}"
            queue = sum(1 for job in self.jobs.values() if job["estado"] in ("queued", "running"))
            step = self.slow_seconds if self.mode == "lento" else self.step_seconds
            now = time.monotonic()
            # Cola: cada trabajo empieza cuando termina el anterior.
            busy_until = max(
                [job["done_at"] for job in self.jobs.values() if job["estado"] != "error"] + [now]
            )
            start = max(now + step, busy_until)
            self.jobs[job_id] = {
                "estado": "queued",
                "created": now,
                "start_at": start,
                "done_at": start + step,
                "fail": self.mode == "error",
                "lost": self.mode == "perdido",
                "volume": random.choice(self.volumes) if self.volumes else None,
            }
            return job_id, queue

    def status(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["lost"]:
                return None
            now = time.monotonic()
            if now >= job["done_at"]:
                job["estado"] = "error" if job["fail"] else "done"
            elif now >= job["start_at"]:
                job["estado"] = "running"
            seconds = round(max(0.0, min(now, job["done_at"]) - job["start_at"]), 1)
            return {
                "job_id": job_id,
                "estado": job["estado"],
                "segundos": seconds,
                "error": "La radiografia no se pudo convertir (simulado)."
                if job["estado"] == "error"
                else None,
            }


def synthetic_volume() -> bytes:
    """Un .nii.gz de 128^3 float32 en [0, 1]: un cuerpo con dos pulmones oscuros."""
    import numpy as np  # solo si hace falta: el resto del simulador no lo necesita

    g = 128
    z, y, x = np.mgrid[0:g, 0:g, 0:g].astype(np.float32) / (g - 1) * 2 - 1
    body = ((y / 0.75) ** 2 + (x / 0.55) ** 2) < 1
    lungs = (((y - 0.35) / 0.28) ** 2 + (x / 0.35) ** 2 + ((z - 0.1) / 0.7) ** 2 < 1) | (
        ((y + 0.35) / 0.28) ** 2 + (x / 0.35) ** 2 + ((z - 0.1) / 0.7) ** 2 < 1
    )
    volume = np.where(body, 0.12, 0.0).astype(np.float32)
    volume[lungs & body] = 0.0
    header = bytearray(348)
    struct.pack_into("<i", header, 0, 348)
    struct.pack_into("<8h", header, 40, 3, g, g, g, 1, 1, 1, 1)
    struct.pack_into("<hh", header, 70, 16, 32)
    struct.pack_into("<8f", header, 76, 1, 2.5, 2.5, 2.5, 1, 1, 1, 1)
    struct.pack_into("<f", header, 108, 352.0)
    struct.pack_into("<f", header, 112, 1.0)
    header[344:348] = b"n+1\x00"
    raw = bytes(header) + b"\x00" * 4 + volume.tobytes(order="F")
    return gzip.compress(raw, compresslevel=1)


def make_handler(state: MockState) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AxonMock/1.0"

        def log_message(self, fmt: str, *args) -> None:  # nunca registra cabeceras
            code = args[1] if len(args) > 1 else ""
            sys.stderr.write(f"[mock {state.mode}] {self.command} {self.path} -> {code}\n")

        # ------------------------------------------------------------- respuestas
        def _send(self, code: int, body: bytes, content_type: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, code: int, payload: dict) -> None:
            self._send(code, json.dumps(payload).encode(), "application/json")

        def _offline(self) -> bool:
            if state.mode == "apagado":
                self._send(404, NGROK_OFFLINE_PAGE, "text/html")
                return True
            return False

        def _authorized(self) -> bool:
            if self.headers.get("X-API-Key") != state.api_key:
                self._json(401, {"detail": "Clave invalida o ausente"})
                return False
            return True

        # ------------------------------------------------------------- rutas
        def do_GET(self) -> None:  # noqa: N802 - nombre que exige http.server
            if self._offline():
                return
            if self.path == "/health":
                with state.lock:
                    queued = sum(1 for j in state.jobs.values() if j["estado"] == "queued")
                    total = len(state.jobs)
                self._json(
                    200, {"estado": "ok", "gpu": "simulada", "en_cola": queued, "trabajos": total}
                )
                return
            match = re.fullmatch(r"/jobs/([A-Za-z0-9_-]+)(/resultado)?", self.path)
            if not match:
                self._json(404, {"detail": "Ruta desconocida"})
                return
            if not self._authorized():
                return
            job_id, wants_result = match.group(1), bool(match.group(2))
            status = state.status(job_id)
            if status is None:
                self._json(404, {"detail": "Trabajo no encontrado"})
                return
            if not wants_result:
                self._json(200, status)
                return
            if status["estado"] != "done":
                self._json(409, {"detail": "El trabajo todavia no termina"})
                return
            volume = state.jobs[job_id]["volume"]
            body = volume.read_bytes() if volume else synthetic_volume()
            self._send(200, body, "application/gzip")

        def do_POST(self) -> None:  # noqa: N802
            # /mock/mode responde siempre, tambien en modo apagado: es el control del simulador.
            if self.path != "/mock/mode" and self._offline():
                return
            if self.path == "/mock/mode":
                length = int(self.headers.get("Content-Length") or 0)
                mode = json.loads(self.rfile.read(length) or b"{}").get("mode")
                if mode not in MODES:
                    self._json(400, {"detail": f"Modo invalido. Usa uno de {MODES}"})
                    return
                state.mode = mode
                self._json(200, {"mode": mode})
                return
            if self.path != "/jobs":
                self._json(404, {"detail": "Ruta desconocida"})
                return
            if not self._authorized():
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_UPLOAD_BYTES:
                self._json(413, {"detail": "Archivo mayor de 60 MB"})
                return
            body = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "")
            message = BytesParser(policy=HTTP).parsebytes(
                f"Content-Type: {content_type}\r\n\r\n".encode() + body
            )
            fields: dict[str, tuple[str | None, bytes]] = {}
            if message.is_multipart():
                for part in message.iter_parts():
                    name = part.get_param("name", header="content-disposition")
                    fields[name] = (part.get_filename(), part.get_payload(decode=True) or b"")
            if "file" not in fields or not fields["file"][1]:
                self._json(400, {"detail": "Falta el campo file"})
                return
            if fields.get("formato", (None, b""))[1].decode() != "normal":
                self._json(400, {"detail": "formato debe ser normal"})
                return
            extension = os.path.splitext(fields["file"][0] or "")[1].lower()
            if extension not in ACCEPTED_EXTENSIONS:
                self._json(400, {"detail": "Extension no admitida"})
                return
            job_id, queue = state.new_job()
            self._json(200, {"job_id": job_id, "en_cola": queue})

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Servicio simulado de AXON")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--key", default=os.environ.get("AXON_MOCK_KEY", "clave-de-prueba"))
    parser.add_argument("--mode", default=os.environ.get("AXON_MOCK_MODE", "ok"), choices=MODES)
    parser.add_argument(
        "--step-seconds",
        type=float,
        default=10.0,
        help="segundos en cola y segundos reconstruyendo (el real tarda ~52 s)",
    )
    parser.add_argument("--slow-seconds", type=float, default=300.0, help="paso del modo lento")
    parser.add_argument(
        "--volumes", type=Path, default=None, help="carpeta con volumenes .nii.gz de ejemplo"
    )
    args = parser.parse_args()

    volumes = sorted(args.volumes.glob("*.nii.gz")) if args.volumes else []
    state = MockState(args.mode, args.key, args.step_seconds, args.slow_seconds, volumes)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(
        f"Simulador de AXON en http://{args.host}:{args.port} · modo {args.mode} · "
        f"{len(volumes) or 'sin'} volumenes de ejemplo",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
