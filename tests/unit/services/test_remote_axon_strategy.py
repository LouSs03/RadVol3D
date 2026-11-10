"""Pruebas de la estrategia remota AXON con un cliente simulado (sin red)."""

import numpy as np
import pytest

from radvol3d import config
from radvol3d.domain.enums import RemoteJobState
from radvol3d.domain.exceptions import (
    ReconstructionServiceUnavailableError,
    RemoteReconstructionError,
)
from radvol3d.persistence.reconstruction_service_client import RemoteJobStatus
from radvol3d.services.reconstruction.remote_axon_strategy import RemoteAxonStrategy
from tests.fixtures.radiograph_files import fake_dicom, nifti_bytes

G = config.GRID_SIZE
UNAVAILABLE = ReconstructionServiceUnavailableError("no disponible")


class ScriptedClient:
    """Responde los estados en orden; un elemento que es una excepcion se lanza."""

    def __init__(self, statuses, alive=True, result=None) -> None:
        self.statuses = list(statuses)
        self.alive = alive
        self.result = (
            result if result is not None else nifti_bytes(np.zeros((G, G, G), dtype=np.float32))
        )
        self.submitted: list[bytes] = []
        self.downloads = 0

    def is_alive(self) -> bool:
        return self.alive

    def submit(self, data: bytes, filename: str = "radiograph.dcm") -> str:
        self.submitted.append(data)
        return "job123"

    def status(self, job_id: str) -> RemoteJobStatus:
        item = self.statuses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return RemoteJobStatus(state=item)

    def download(self, job_id: str) -> bytes:
        self.downloads += 1
        return self.result


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def strategy(client, clock=None, max_wait=900.0) -> RemoteAxonStrategy:
    clock = clock or FakeClock()
    return RemoteAxonStrategy(
        client, poll_seconds=5.0, max_wait_seconds=max_wait, sleep=clock.sleep, clock=clock
    )


@pytest.mark.unit
def test_a_finished_job_is_downloaded_and_converted_to_the_system_volume() -> None:
    client = ScriptedClient(["queued", "queued", "running", "done"])
    states: list[RemoteJobState] = []
    clock = FakeClock()

    volume = strategy(client, clock).reconstruct(fake_dicom(), states.append)

    assert client.submitted == [fake_dicom()]
    assert client.downloads == 1
    assert volume.shape == (G, G, G) and volume.dtype == np.float32
    # Un volumen de ceros del servicio (-100 HU) queda en 0,45 en la ventana del sistema.
    assert float(volume.max()) == pytest.approx(0.45)
    # Cada estado se avisa una sola vez, aunque se repita en la consulta.
    assert states == [RemoteJobState.QUEUED, RemoteJobState.RUNNING]
    assert clock.sleeps == [5.0, 5.0, 5.0]


@pytest.mark.unit
def test_a_job_that_ends_in_error_fails_with_the_reason() -> None:
    client = ScriptedClient(["running", "error"])

    with pytest.raises(RemoteReconstructionError, match="no pudo reconstruir"):
        strategy(client).reconstruct(fake_dicom())
    assert client.downloads == 0


@pytest.mark.unit
def test_a_lost_job_fails_so_the_study_can_be_retried() -> None:
    client = ScriptedClient(["queued", RemoteReconstructionError("El trabajo ya no existe")])

    with pytest.raises(RemoteReconstructionError, match="ya no existe"):
        strategy(client).reconstruct(fake_dicom())


@pytest.mark.unit
def test_a_service_that_is_off_fails_fast_without_sending_anything() -> None:
    client = ScriptedClient([], alive=False)

    with pytest.raises(ReconstructionServiceUnavailableError):
        strategy(client).reconstruct(fake_dicom())
    assert client.submitted == []


@pytest.mark.unit
def test_a_short_outage_while_waiting_is_tolerated() -> None:
    client = ScriptedClient(["running", UNAVAILABLE, UNAVAILABLE, "done"])

    volume = strategy(client).reconstruct(fake_dicom())

    assert volume.shape == (G, G, G)


@pytest.mark.unit
def test_three_outages_in_a_row_give_up() -> None:
    client = ScriptedClient(["running", UNAVAILABLE, UNAVAILABLE, UNAVAILABLE, "done"])

    with pytest.raises(ReconstructionServiceUnavailableError):
        strategy(client).reconstruct(fake_dicom())


@pytest.mark.unit
def test_the_total_wait_is_bounded() -> None:
    client = ScriptedClient(["running"] * 100)
    clock = FakeClock()

    with pytest.raises(RemoteReconstructionError, match="tardó demasiado"):
        strategy(client, clock, max_wait=20.0).reconstruct(fake_dicom())
    assert clock.now <= 25.0


@pytest.mark.unit
def test_a_failing_reporter_does_not_stop_the_job() -> None:
    client = ScriptedClient(["running", "done"])

    def broken(state) -> None:
        raise RuntimeError("la interfaz fallo")

    assert strategy(client).reconstruct(fake_dicom(), broken).shape == (G, G, G)


@pytest.mark.unit
def test_availability_is_the_health_of_the_service() -> None:
    assert strategy(ScriptedClient([], alive=True)).is_available() is True
    assert strategy(ScriptedClient([], alive=False)).is_available() is False
