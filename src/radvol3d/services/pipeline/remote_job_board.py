"""Pizarra en memoria: en que paso va el trabajo externo de cada estudio.

Mientras un estudio de una radiografia esta en la etapa 2, la interfaz puede mostrar
"en cola" o "reconstruyendo" (seccion 4.2 de la guia). Ese dato cambia cada pocos
segundos y no vale nada despues, asi que no se guarda en la base: vive aqui, en la
memoria del proceso. Funciona porque el servicio corre con un solo worker (--workers 1).

Si el proceso se reinicia, la pizarra queda vacia y el estudio interrumpido pasa a
failed al arrancar, como cualquier otro.
"""

import threading

from radvol3d.domain.enums import RemoteJobState


class RemoteJobBoard:
    """Estado del trabajo externo por codigo de estudio. Segura entre hilos."""

    def __init__(self) -> None:
        self._states: dict[str, RemoteJobState] = {}
        self._lock = threading.Lock()

    def update(self, study_code: str, state: RemoteJobState) -> None:
        with self._lock:
            self._states[study_code] = RemoteJobState(state)

    def get(self, study_code: str) -> RemoteJobState | None:
        with self._lock:
            return self._states.get(study_code)

    def clear(self, study_code: str) -> None:
        with self._lock:
            self._states.pop(study_code, None)
