"""Pruebas de la subida de proyecciones con el servicio simulado (research.md R7)."""

import pytest
from fastapi import HTTPException

from radvol3d import config
from radvol3d.api.routers import projection_router
from radvol3d.domain.entities import Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.services.pipeline.projection_loader import ProjectionFile
from tests.fixtures.projection_files import valid_npy

CODE = "lung_028"
FIELDS = {0: "angle_000", 45: "angle_045", 90: "angle_090", 135: "angle_135"}


def four_files(**replacements: bytes) -> dict:
    files = {
        field: (f"{field}.npy", valid_npy(angle), "application/octet-stream")
        for angle, field in FIELDS.items()
    }
    for field, content in replacements.items():
        files[field] = (f"{field}.npy", content, "application/octet-stream")
    return files


@pytest.fixture
def service(client):
    service = client.app.state.services.study_service
    service.add_projections.return_value = Study(CODE, OrganName.LUNG, StudyStatus.PENDING)
    return service


@pytest.mark.unit
def test_four_files_are_stored_and_the_angles_confirmed(client, service) -> None:
    response = client.post(f"/studies/{CODE}/projections", files=four_files())

    assert response.status_code == 201
    assert response.json() == {"study_code": CODE, "angles": [0, 45, 90, 135]}
    code, files = service.add_projections.call_args.args
    assert code == CODE
    assert [f.angle_degrees for f in files] == [0, 45, 90, 135]
    assert all(isinstance(f, ProjectionFile) for f in files)
    assert files[1].content == valid_npy(45)


@pytest.mark.unit
def test_the_angle_comes_from_the_field_not_from_the_file_name(client, service) -> None:
    files = four_files()
    files["angle_000"] = ("angulo_135.npy", valid_npy(0), "application/octet-stream")

    client.post(f"/studies/{CODE}/projections", files=files)

    stored = service.add_projections.call_args.args[1]
    assert stored[0].angle_degrees == 0
    assert stored[0].original_name == "angulo_135.npy"


@pytest.mark.unit
def test_a_missing_field_is_a_validation_error(client, service) -> None:
    files = four_files()
    del files["angle_090"]

    response = client.post(f"/studies/{CODE}/projections", files=files)

    assert response.status_code == 422
    service.add_projections.assert_not_called()


@pytest.mark.unit
def test_a_file_over_the_limit_is_rejected_naming_angle_and_limit(client, service) -> None:
    too_big = b"\x00" * (config.MAX_PROJECTION_BYTES + 1)

    response = client.post(
        f"/studies/{CODE}/projections", files=four_files(angle_045=too_big)
    )

    assert response.status_code == 413
    detail = response.json()["detail"]
    assert "45" in detail
    assert "1 MiB" in detail
    service.add_projections.assert_not_called()


class CountingUpload:
    """UploadFile doble que anota cuantos bytes le piden."""

    def __init__(self, size: int) -> None:
        self.filename = "grande.npy"
        self.requested: list[int] = []
        self._size = size

    async def read(self, size: int = -1) -> bytes:
        self.requested.append(size)
        return b"\x00" * (self._size if size < 0 else min(size, self._size))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_router_reads_at_most_one_byte_over_the_limit() -> None:
    upload = CountingUpload(size=10 * config.MAX_PROJECTION_BYTES)

    with pytest.raises(HTTPException) as raised:
        await projection_router.read_limited(upload, angle=45)  # type: ignore[arg-type]

    assert raised.value.status_code == 413
    assert upload.requested == [config.MAX_PROJECTION_BYTES + 1]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_file_within_the_limit_is_read_whole() -> None:
    upload = CountingUpload(size=100)

    content = await projection_router.read_limited(upload, angle=0)  # type: ignore[arg-type]

    assert content == b"\x00" * 100
