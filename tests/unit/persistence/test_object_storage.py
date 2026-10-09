"""Pruebas del almacenamiento de objetos, con un bucket en memoria."""

import io
import logging
from types import SimpleNamespace

import httpx
import numpy as np
import pytest
from pydantic import SecretStr
from storage3.utils import StorageException

from radvol3d.domain.exceptions import StorageError, StorageObjectNotFoundError
from radvol3d.persistence import object_storage as object_storage_module
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.settings import Settings
from tests.fixtures.fake_object_storage import InMemoryBucket

PATH = "it_estudio/volume.npy"


@pytest.fixture
def bucket() -> InMemoryBucket:
    return InMemoryBucket()


@pytest.fixture
def storage(bucket: InMemoryBucket) -> ObjectStorage:
    return ObjectStorage(bucket)


@pytest.mark.unit
def test_uploaded_bytes_come_back_identical(storage: ObjectStorage) -> None:
    storage.upload_bytes("it_a/segmentation/summary.json", b'{"a": 1}', "application/json")

    assert storage.download_bytes("it_a/segmentation/summary.json") == b'{"a": 1}'


@pytest.mark.unit
def test_uploading_to_an_occupied_path_replaces_the_file(storage: ObjectStorage) -> None:
    storage.upload_bytes(PATH, b"primero", "application/octet-stream")

    storage.upload_bytes(PATH, b"segundo", "application/octet-stream")

    assert storage.download_bytes(PATH) == b"segundo"


@pytest.mark.unit
def test_exists_reports_whether_the_file_is_there(storage: ObjectStorage) -> None:
    storage.upload_bytes(PATH, b"x", "application/octet-stream")

    assert storage.exists(PATH) is True
    assert storage.exists("it_otro/volume.npy") is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "content_type"),
    [
        ("it_a/segmentation/summary.json", "application/json"),
        ("it_a/meshes/tumor.glb", "model/gltf-binary"),
        ("it_a/volume.npy", "application/octet-stream"),
    ],
)
def test_the_content_type_is_sent_with_the_file(
    storage: ObjectStorage, bucket: InMemoryBucket, path: str, content_type: str
) -> None:
    storage.upload_bytes(path, b"x", content_type)

    assert bucket.content_types[path] == content_type


@pytest.mark.unit
def test_an_array_comes_back_equal_with_its_shape_and_type(storage: ObjectStorage) -> None:
    volume = np.arange(24, dtype=np.float32).reshape(2, 3, 4)

    storage.upload_array(PATH, volume)
    loaded = storage.download_array(PATH)

    assert loaded.dtype == np.float32
    assert loaded.shape == (2, 3, 4)
    assert np.array_equal(loaded, volume)


@pytest.mark.unit
def test_arrays_are_uploaded_as_octet_stream(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    storage.upload_array(PATH, np.zeros(3, dtype=np.uint8))

    assert bucket.content_types[PATH] == "application/octet-stream"


@pytest.mark.unit
def test_a_npy_file_with_serialized_objects_is_rejected(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    buffer = io.BytesIO()
    np.save(buffer, np.array([{"clave": 1}], dtype=object), allow_pickle=True)
    bucket.files[PATH] = buffer.getvalue()

    with pytest.raises(StorageError) as raised:
        storage.download_array(PATH)

    assert type(raised.value) is StorageError


@pytest.mark.unit
def test_bytes_that_are_not_a_npy_file_are_rejected(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    bucket.files[PATH] = b"esto no es un arreglo"

    with pytest.raises(StorageError):
        storage.download_array(PATH)


@pytest.mark.unit
def test_an_object_array_is_never_uploaded(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    with pytest.raises(StorageError):
        storage.upload_array(PATH, np.array([{"clave": 1}], dtype=object))

    assert bucket.files == {}


@pytest.mark.unit
def test_downloading_a_missing_file_raises_not_found(storage: ObjectStorage) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        storage.download_bytes("it_no_existe/volume.npy")


@pytest.mark.unit
def test_not_found_is_also_a_storage_error(storage: ObjectStorage) -> None:
    with pytest.raises(StorageError):
        storage.download_array("it_no_existe/volume.npy")


@pytest.mark.unit
def test_an_access_failure_is_not_reported_as_not_found(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    storage.upload_bytes(PATH, b"x", "application/octet-stream")
    bucket.fail_next("download", StorageException("acceso denegado"))

    with pytest.raises(StorageError) as raised:
        storage.download_bytes(PATH)

    assert type(raised.value) is StorageError


@pytest.mark.unit
def test_a_failed_upload_raises_a_storage_error(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    bucket.fail_next("upload", StorageException("cuota excedida"))

    with pytest.raises(StorageError):
        storage.upload_bytes(PATH, b"x", "application/octet-stream")


@pytest.mark.unit
def test_a_failed_exists_raises_a_storage_error(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    bucket.fail_next("exists", StorageException("sin acceso"))

    with pytest.raises(StorageError):
        storage.exists(PATH)


@pytest.mark.unit
def test_a_network_failure_raises_a_storage_error(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    bucket.fail_next("upload", httpx.ConnectError("sin red"))

    with pytest.raises(StorageError):
        storage.upload_bytes(PATH, b"x", "application/octet-stream")


@pytest.mark.unit
def test_storage_errors_have_a_message_in_spanish_and_no_cause(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    bucket.fail_next("upload", StorageException("detalle interno con una-clave-secreta"))

    with pytest.raises(StorageError) as raised:
        storage.upload_bytes(PATH, b"x", "application/octet-stream")

    assert "una-clave-secreta" not in str(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.unit
def test_from_settings_builds_the_bucket_client(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}
    bucket = InMemoryBucket()

    class FakeStorageClient:
        def from_(self, bucket_name: str) -> InMemoryBucket:
            calls["bucket_name"] = bucket_name
            return bucket

    def fake_create_client(url: str, key: str) -> SimpleNamespace:
        calls["url"] = url
        calls["key"] = key
        return SimpleNamespace(storage=FakeStorageClient())

    monkeypatch.setattr(object_storage_module, "create_client", fake_create_client)
    settings = Settings(
        _env_file=None,
        database_url=SecretStr("postgresql://user:pass@host/db"),
        supabase_url="https://project.example",
        supabase_service_key=SecretStr("service-key-value-1"),
        storage_bucket="bucket-de-prueba",
    )

    storage = ObjectStorage.from_settings(settings)

    assert calls == {
        "url": "https://project.example",
        "key": "service-key-value-1",
        "bucket_name": "bucket-de-prueba",
    }
    storage.upload_bytes(PATH, b"x", "application/octet-stream")
    assert bucket.files[PATH] == b"x"


# --- Los registros DEBUG de hpack escriben la cabecera apikey con la clave de servicio ---


def _settings_with_a_service_key() -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr("postgresql://user:pass@host/db"),
        supabase_url="https://project.example",
        supabase_service_key=SecretStr("service-key-value-1"),
        storage_bucket="bucket-de-prueba",
    )


@pytest.fixture
def fake_supabase_client(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SimpleNamespace(storage=SimpleNamespace(from_=lambda name: InMemoryBucket()))
    monkeypatch.setattr(object_storage_module, "create_client", lambda url, key: client)


@pytest.fixture
def restore_hpack_level() -> None:
    logger = logging.getLogger("hpack")
    previous = logger.level
    yield
    logger.setLevel(previous)


@pytest.mark.unit
def test_from_settings_keeps_the_credentials_out_of_debug_logs(
    fake_supabase_client: None,
    restore_hpack_level: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    logging.getLogger("hpack").setLevel(logging.NOTSET)

    ObjectStorage.from_settings(_settings_with_a_service_key())

    with caplog.at_level(logging.DEBUG):
        logging.getLogger("hpack.hpack").debug("Adding b'apikey'=b'service-key-value-1'")
        logging.getLogger("hpack.table").debug("Evicting b'apikey': b'service-key-value-1'")
    assert "service-key-value-1" not in caplog.text


@pytest.mark.unit
def test_from_settings_does_not_lower_a_stricter_level(
    fake_supabase_client: None, restore_hpack_level: None
) -> None:
    logging.getLogger("hpack").setLevel(logging.ERROR)

    ObjectStorage.from_settings(_settings_with_a_service_key())

    assert logging.getLogger("hpack").level == logging.ERROR
