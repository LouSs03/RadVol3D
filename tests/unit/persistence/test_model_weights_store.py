"""Pruebas de la descarga de pesos con cache local (research.md R10)."""

from pathlib import Path

import pytest
from storage3.utils import StorageException

from radvol3d.domain.exceptions import StorageError, StorageObjectNotFoundError
from radvol3d.persistence.model_weights_store import ModelWeightsStore
from radvol3d.persistence.object_storage import ObjectStorage
from tests.fixtures.fake_object_storage import InMemoryBucket

OBJECT = "reconstruction_en1/1.0.0/weights.pth"
WEIGHTS = b"\x80\x02pesos de prueba" * 100


@pytest.fixture
def bucket() -> InMemoryBucket:
    bucket = InMemoryBucket()
    bucket.files[OBJECT] = WEIGHTS
    return bucket


@pytest.fixture
def store(bucket: InMemoryBucket, tmp_path: Path) -> ModelWeightsStore:
    return ModelWeightsStore(ObjectStorage(bucket), tmp_path / "cache")


def downloads(bucket: InMemoryBucket) -> list[str]:
    return [e for e in bucket.events if e.startswith("download:")]


@pytest.mark.unit
def test_the_first_fetch_downloads_the_file_into_the_cache(
    store: ModelWeightsStore, bucket: InMemoryBucket, tmp_path: Path
) -> None:
    path = store.fetch(OBJECT)

    assert path == tmp_path / "cache" / OBJECT
    assert path.read_bytes() == WEIGHTS
    assert downloads(bucket) == [f"download:{OBJECT}"]


@pytest.mark.unit
def test_the_second_fetch_does_not_download_again(
    store: ModelWeightsStore, bucket: InMemoryBucket
) -> None:
    first = store.fetch(OBJECT)
    second = store.fetch(OBJECT)

    assert first == second
    assert len(downloads(bucket)) == 1


@pytest.mark.unit
def test_a_missing_object_raises_not_found_and_leaves_no_file(
    store: ModelWeightsStore, tmp_path: Path
) -> None:
    with pytest.raises(StorageObjectNotFoundError):
        store.fetch("segmentation_lung/1.0.0/weights.pth")

    cache = tmp_path / "cache"
    assert not cache.exists() or not any(p.is_file() for p in cache.rglob("*"))


@pytest.mark.unit
def test_a_failed_download_leaves_no_partial_file(
    store: ModelWeightsStore, bucket: InMemoryBucket, tmp_path: Path
) -> None:
    bucket.fail_next("download", StorageException("se corto la conexion"))
    bucket.fail_next("exists", StorageException("sin red"))

    with pytest.raises(StorageError):
        store.fetch(OBJECT)

    cache = tmp_path / "cache"
    assert not cache.exists() or not any(p.is_file() for p in cache.rglob("*"))


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad", ["../fuera.pth", "a/../../fuera.pth", "a\\b.pth", "", "/abs.pth"]
)
def test_a_dangerous_path_is_rejected_before_downloading(
    store: ModelWeightsStore, bucket: InMemoryBucket, bad: str
) -> None:
    with pytest.raises(StorageError):
        store.fetch(bad)

    assert downloads(bucket) == []
