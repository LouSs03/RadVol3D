"""Pruebas del cliente del servicio AXON contra el simulador (scripts/axon_mock_server.py).

El simulador corre en un hilo, en 127.0.0.1 y en un puerto libre: no sale a internet.
Cubre los casos de la seccion 6.3 de la guia que tocan al cliente: servicio encendido,
apagado (pagina HTML de ngrok), trabajo con error, trabajo perdido y clave incorrecta.
"""

import importlib.util
import threading
from pathlib import Path

import pytest

from radvol3d.domain.exceptions import (
    ReconstructionServiceUnavailableError,
    RemoteReconstructionError,
)
from radvol3d.persistence.reconstruction_service_client import (
    ReconstructionServiceClient,
    _multipart,
)
from radvol3d.persistence.settings import ReconstructionServiceSettings
from tests.fixtures.radiograph_files import fake_dicom

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "axon_mock_server.py"
KEY = "clave-de-prueba"


def load_mock():
    spec = importlib.util.spec_from_file_location("axon_mock_server", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def mock_service():
    module = load_mock()
    state = module.MockState("ok", KEY, step_seconds=0.0, slow_seconds=0.0, volumes=[])
    server = module.ThreadingHTTPServer(("127.0.0.1", 0), module.make_handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield state, f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def client_for(url: str, key: str = KEY) -> ReconstructionServiceClient:
    return ReconstructionServiceClient(url, key, health_timeout=2, upload_timeout=5)


@pytest.mark.unit
def test_a_job_goes_from_submit_to_the_downloaded_volume(mock_service) -> None:
    state, url = mock_service
    client = client_for(url)

    assert client.is_alive() is True
    job_id = client.submit(fake_dicom())
    status = client.status(job_id)
    volume = client.download(job_id)

    assert status.state == "done"
    assert volume[:2] == b"\x1f\x8b"  # .nii.gz


@pytest.mark.unit
def test_with_the_tunnel_off_the_service_is_unavailable_and_html_is_never_parsed(
    mock_service,
) -> None:
    state, url = mock_service
    state.mode = "apagado"
    client = client_for(url)

    assert client.is_alive() is False
    with pytest.raises(ReconstructionServiceUnavailableError):
        client.submit(fake_dicom())


@pytest.mark.unit
def test_a_job_in_error_reports_the_reason(mock_service) -> None:
    state, url = mock_service
    state.mode = "error"
    client = client_for(url)

    status = client.status(client.submit(fake_dicom()))

    assert status.state == "error"
    assert status.error


@pytest.mark.unit
def test_a_lost_job_is_a_reconstruction_error(mock_service) -> None:
    state, url = mock_service
    state.mode = "perdido"
    client = client_for(url)
    job_id = client.submit(fake_dicom())

    with pytest.raises(RemoteReconstructionError, match="ya no existe"):
        client.status(job_id)


@pytest.mark.unit
def test_a_wrong_key_is_rejected_without_showing_it(mock_service) -> None:
    _, url = mock_service
    client = client_for(url, key="clave-mala")

    with pytest.raises(RemoteReconstructionError) as caught:
        client.submit(fake_dicom())

    assert "clave-mala" not in str(caught.value)
    assert url not in str(caught.value)


@pytest.mark.unit
def test_a_service_that_does_not_answer_is_unavailable_quickly() -> None:
    # El puerto 9 (discard) no tiene a nadie escuchando en 127.0.0.1.
    client = ReconstructionServiceClient("http://127.0.0.1:9", KEY, health_timeout=1)

    assert client.is_alive() is False
    with pytest.raises(ReconstructionServiceUnavailableError):
        client.status("abc123")


@pytest.mark.unit
@pytest.mark.parametrize("job_id", ["../health", "a/b", "", "x" * 65])
def test_a_strange_job_id_never_builds_another_path(job_id: str) -> None:
    client = ReconstructionServiceClient("http://127.0.0.1:9", KEY)

    with pytest.raises(RemoteReconstructionError):
        client.status(job_id)


@pytest.mark.unit
def test_the_key_and_the_address_never_appear_in_repr() -> None:
    client = ReconstructionServiceClient("https://servicio.ejemplo.dev", "secreto123")

    assert "secreto123" not in repr(client)
    assert "ejemplo" not in repr(client)


@pytest.mark.unit
def test_without_address_or_key_there_is_no_client() -> None:
    # Valores explicitos: el .env del desarrollador no debe influir en la prueba.
    empty = ReconstructionServiceSettings(axon_url=None, axon_api_key=None)
    assert ReconstructionServiceClient.from_settings(empty) is None
    assert (
        ReconstructionServiceClient.from_settings(
            ReconstructionServiceSettings(axon_url="https://x.dev", axon_api_key="k")
        )
        is not None
    )


@pytest.mark.unit
def test_the_multipart_body_has_the_file_and_the_format_field() -> None:
    body = _multipart("B", {"formato": "normal"}, {"file": ("r.dcm", b"DATA", "application/dicom")})

    assert b'name="formato"\r\n\r\nnormal' in body
    assert b'name="file"; filename="r.dcm"' in body
    assert body.endswith(b"--B--\r\n")
