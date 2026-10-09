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


# --- remove_many (funcionalidad 002, borrado de estudios) ---


@pytest.mark.unit
def test_remove_many_deletes_every_path_in_a_single_call(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    for name in ("a.npy", "b.npy", "c.npy"):
        storage.upload_bytes(f"it_x/{name}", b"x", "application/octet-stream")

    storage.remove_many(["it_x/a.npy", "it_x/b.npy"])

    assert bucket.uploaded_paths() == ["it_x/c.npy"]
    assert [e for e in bucket.events if e.startswith("remove:")] == [
        "remove:it_x/a.npy,it_x/b.npy"
    ]


@pytest.mark.unit
def test_removing_a_missing_path_is_not_an_error(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    storage.remove_many(["it_x/no_existe.npy"])

    assert bucket.files == {}


@pytest.mark.unit
def test_removing_nothing_does_not_call_the_bucket(
    storage: ObjectStorage, bucket: InMemoryBucket
) -> None:
    storage.remove_many([])

    assert bucket.events == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "error", [StorageException("permiso denegado sk-123"), httpx.ConnectError("sin red")]
)
def test_a_failed_remove_raises_a_storage_error_without_the_original_text(
    storage: ObjectStorage, bucket: InMemoryBucket, error: Exception
) -> None:
    bucket.fail_next("remove", error)

    with pytest.raises(StorageError) as caught:
        storage.remove_many(["it_x/a.npy"])

    assert "sk-123" not in str(caught.value)
    assert "sin red" not in str(caught.value)
    assert caught.value.__cause__ is None


# --- from_settings con otro bucket (bucket de modelos) ---


@pytest.mark.unit
@pytest.mark.parametrize(("bucket_name", "expected"), [("modelos-x", "modelos-x"), (None, "bucket-de-prueba")])
def test_from_settings_can_open_another_bucket(
    monkeypatch: pytest.MonkeyPatch, bucket_name: str | None, expected: str
) -> None:
    opened: list[str] = []

    class FakeStorageClient:
        def from_(self, name: str) -> InMemoryBucket:
            opened.append(name)
            return InMemoryBucket()

    monkeypatch.setattr(
        object_storage_module,
        "create_client",
        lambda url, key: SimpleNamespace(storage=FakeStorageClient()),
    )

    ObjectStorage.from_settings(_settings_with_a_service_key(), bucket=bucket_name)

    assert opened == [expected]


# --- Concurrencia (funcionalidad 002, FR-020) ---
# El cliente HTTP de Supabase no admite dos peticiones a la vez desde hilos distintos:
# con dos estudios en paralelo, la subida fallaba con httpx.ReadError (WinError 10035).


class OverlapDetectingBucket(InMemoryBucket):
    """Bucket que se demora en cada llamada y anota si dos llamadas se solaparon."""

    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self._counter = __import__("threading").Lock()

    def _enter(self) -> None:
        import time

        with self._counter:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.01)
        with self._counter:
            self.active -= 1

    def upload(self, path, file, file_options=None):
        self._enter()
        return super().upload(path, file, file_options)

    def download(self, path):
        self._enter()
        return super().download(path)

    def exists(self, path):
        self._enter()
        return super().exists(path)

    def remove(self, paths):
        self._enter()
        return super().remove(paths)


@pytest.mark.unit
def test_calls_from_several_threads_never_reach_the_bucket_at_the_same_time() -> None:
    from concurrent.futures import ThreadPoolExecutor

    bucket = OverlapDetectingBucket()
    storage = ObjectStorage(bucket)

    def work(n: int) -> None:
        path = f"it_x/{n}.bin"
        storage.upload_bytes(path, b"x", "application/octet-stream")
        storage.exists(path)
        storage.download_bytes(path)
        storage.remove_many([path])

    with ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(work, range(12)))

    assert bucket.max_active == 1
    assert bucket.files == {}


# --- list_names (funcionalidad 004, research.md R12) ---


@pytest.mark.unit
def test_list_names_returns_only_the_files_directly_in_the_folder(
    bucket: InMemoryBucket, storage: ObjectStorage
) -> None:
    for path in (
        "it_a/meshes/organ.glb",
        "it_a/meshes/lesion_001.glb",
        "it_a/meshes/lesion_002.glb",
        "it_a/volume.npy",
        "it_a/segmentation/mask.npy",
        "it_ab/meshes/lesion_001.glb",
    ):
        bucket.files[path] = b"x"

    assert storage.list_names("it_a/meshes") == ["lesion_001.glb", "lesion_002.glb", "organ.glb"]
    assert storage.list_names("it_a") == ["volume.npy"]


@pytest.mark.unit
def test_an_empty_or_missing_folder_has_no_names(storage: ObjectStorage) -> None:
    assert storage.list_names("it_no_existe/meshes") == []


@pytest.mark.unit
def test_a_failing_list_is_a_storage_error_without_the_key(
    bucket: InMemoryBucket, storage: ObjectStorage
) -> None:
    bucket.fail_next("list", StorageException("fallo con una-clave-secreta"))

    with pytest.raises(StorageError) as raised:
        storage.list_names("it_a/meshes")

    assert "una-clave-secreta" not in str(raised.value)
