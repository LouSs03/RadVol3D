"""Reconstruccion desde una radiografia con el servicio externo AXON CoarseDiff.

El modelo pesa 265 MB y necesita GPU: no cabe en el Contabo (sin GPU) ni en el bucket
de Supabase (50 MB por archivo). Corre en Colab, detras de un tunel ngrok, y esta
estrategia solo habla con el (persistence/reconstruction_service_client.py).

Corre dentro de la tarea en segundo plano del estudio, nunca dentro de la peticion del
usuario: enviar, consultar cada pocos segundos y descargar puede tardar cerca de un
minuto por trabajo, mas si hay cola. La espera total esta acotada (15 minutos por
omision); si se agota, el trabajo falla y el estudio queda failed.

Que hace con cada estado del servicio (seccion 4.2 de la guia):

- queued / running: avisa a la interfaz y sigue esperando.
- done: descarga el .nii.gz, lo lee y lo lleva al convenio del sistema (nifti_volume).
- error: falla con el motivo que da el servicio.
- 404 (trabajo perdido, por ejemplo si Colab se reinicio): falla y se puede reintentar.
- sin respuesta: tras unos intentos seguidos, falla como servicio no disponible.

Gancho para la segmentacion de Lourdes (requisito 8): esta estrategia solo reconstruye.
La segmentacion del volumen generado es la etapa 3 de la tuberia, con la estrategia
que entregue StrategyFactory.radiograph_strategies_for (hoy PendingSegmentationStrategy).
"""

import logging
import time
from collections.abc import Callable
from typing import Any

from radvol3d.domain.enums import RemoteJobState
from radvol3d.domain.exceptions import (
    ReconstructionServiceUnavailableError,
    RemoteReconstructionError,
)
from radvol3d.persistence.reconstruction_service_client import (
    DONE,
    ERROR,
    QUEUED,
    ReconstructionServiceClient,
)
from radvol3d.services.reconstruction.nifti_volume import read_nifti, to_system_volume
from radvol3d.services.reconstruction.radiograph_reconstruction_strategy import (
    RadiographReconstructionStrategy,
    StateReporter,
)

logger = logging.getLogger(__name__)

MODEL_NAME = "reconstruction_axon_coarsediff"
MODEL_VERSION = "remote-1"

# Cuantas consultas de estado seguidas sin respuesta se toleran antes de rendirse. Un
# corte breve del tunel no deberia tirar un trabajo que ya esta en la GPU.
MAX_CONSECUTIVE_UNREACHABLE = 3


class RemoteAxonStrategy(RadiographReconstructionStrategy):
    """Envia el DICOM al servicio AXON, espera el resultado y lo convierte."""

    def __init__(
        self,
        client: ReconstructionServiceClient,
        *,
        poll_seconds: float = 5.0,
        max_wait_seconds: float = 900.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._poll_seconds = poll_seconds
        self._max_wait_seconds = max_wait_seconds
        self._sleep = sleep
        self._clock = clock

    @property
    def model_name(self) -> str:
        return MODEL_NAME

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def is_available(self) -> bool:
        return self._client.is_alive()

    def reconstruct(self, radiograph: bytes, report: StateReporter | None = None) -> Any:
        if not self._client.is_alive():
            raise ReconstructionServiceUnavailableError(
                "El modo de una radiografía no está disponible en este momento."
            )
        job_id = self._client.submit(radiograph)
        logger.info("Radiografia enviada al servicio de reconstruccion (trabajo %s)", job_id)
        self._wait_until_done(job_id, report)
        volume = read_nifti(self._client.download(job_id))
        return to_system_volume(volume)

    def _wait_until_done(self, job_id: str, report: StateReporter | None) -> None:
        deadline = self._clock() + self._max_wait_seconds
        unreachable = 0
        last_state: str | None = None
        while True:
            try:
                status = self._client.status(job_id)
                unreachable = 0
            except ReconstructionServiceUnavailableError:
                unreachable += 1
                if unreachable >= MAX_CONSECUTIVE_UNREACHABLE:
                    raise
                status = None
            if status is not None:
                if status.state == DONE:
                    return
                if status.state == ERROR:
                    raise RemoteReconstructionError(
                        "El servicio no pudo reconstruir esta radiografía"
                        + (f": {status.error}" if status.error else ".")
                    )
                if status.state != last_state:
                    last_state = status.state
                    _report(
                        report,
                        RemoteJobState.QUEUED if status.state == QUEUED else RemoteJobState.RUNNING,
                    )
            if self._clock() >= deadline:
                raise RemoteReconstructionError(
                    "El servicio de reconstrucción tardó demasiado. Vuelve a intentarlo."
                )
            self._sleep(self._poll_seconds)


def _report(report: StateReporter | None, state: RemoteJobState) -> None:
    if report is None:
        return
    try:
        report(state)
    except Exception as error:  # noqa: BLE001 - avisar a la interfaz nunca tumba el trabajo
        logger.warning("No se pudo avisar el estado del trabajo (%s)", type(error).__name__)
