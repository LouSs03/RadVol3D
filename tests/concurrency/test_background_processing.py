"""El procesamiento en segundo plano no bloquea las consultas (FR-032, SC-003).

Levanta uvicorn de verdad en un hilo: TestClient corre las tareas en segundo plano de
forma sincronica y ocultaria justo lo que se quiere comprobar. El servicio es un doble
cuyo run_processing espera un evento, como una tuberia que tarda; mientras espera, se
consulta el estado de otro estudio. No usa la base ni el bucket.
"""

import socket
import threading
import time
from collections.abc import Iterator

import httpx
import pytest
import uvicorn

from radvol3d.domain.entities import Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.main import create_app

pytestmark = pytest.mark.concurrency

STATUS_QUERIES = 10
MAX_SECONDS = 1.0


class SlowService:
    """StudyService doble: run_processing no termina hasta que se libera el evento."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.processing_started = threading.Event()

    def start_processing(self, study_code: str) -> Study:
        return Study(study_code, OrganName.LUNG, StudyStatus.PROCESSING)

    def run_processing(self, study_code: str) -> None:
        self.processing_started.set()
        self.release.wait(timeout=30)

    def get_study(self, study_code: str) -> Study:
        return Study(study_code, OrganName.LUNG, StudyStatus.PENDING)


class SlowContainer:
    def __init__(self, service: SlowService) -> None:
        self.study_service = service

    def model_status(self) -> dict[str, bool]:
        return {}

    def close(self) -> None:
        pass


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def running_server() -> Iterator[tuple[str, SlowService]]:
    service = SlowService()
    app = create_app(container_builder=lambda: SlowContainer(service))
    port = free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "uvicorn no arranco"
    try:
        yield f"http://127.0.0.1:{port}", service
    finally:
        service.release.set()
        server.should_exit = True
        thread.join(timeout=10)


def test_status_queries_answer_fast_while_another_study_is_processed(
    running_server: tuple[str, SlowService],
) -> None:
    base_url, service = running_server

    with httpx.Client(base_url=base_url, timeout=5) as client:
        accepted = client.post("/studies/it_lento/process")
        assert accepted.status_code == 202
        assert service.processing_started.wait(timeout=5)

        durations = []
        for _ in range(STATUS_QUERIES):
            started = time.perf_counter()
            response = client.get("/studies/it_otro/status")
            durations.append(time.perf_counter() - started)
            assert response.status_code == 200

    assert not service.release.is_set(), "la tuberia doble termino antes de tiempo"
    assert max(durations) < MAX_SECONDS
