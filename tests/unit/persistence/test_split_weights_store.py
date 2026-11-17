"""Pruebas de los pesos partidos: bajar, unir, verificar la huella y usar la cache."""

import hashlib
from pathlib import Path

import pytest

from radvol3d.domain.exceptions import StorageError
from radvol3d.persistence.split_weights_store import (
    SplitWeightsStore,
    WeightsIntegrityError,
    sha256_hex,
)

OBJECT = "reconstruction_x2ct/1.0.0/weights.pth"
WEIGHTS = bytes(range(256)) * 400  # 100 KiB de "pesos"
PREFIX = hashlib.sha256(WEIGHTS).hexdigest()[:12]


class PartsBucket:
    """Un bucket de modelos con los pesos partidos; anota cada descarga."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files
        self.downloads: list[str] = []

    def list_names(self, folder: str) -> list[str]:
        prefix = folder + "/"
        return sorted(p[len(prefix) :] for p in self.files if p.startswith(prefix) and "/" not in p[len(prefix) :])

    def download_bytes(self, path: str) -> bytes:
        self.downloads.append(path)
        return self.files[path]


def split_into(data: bytes, parts: int) -> dict[str, bytes]:
    size = -(-len(data) // parts)
    return {f"{OBJECT}.part{i:02d}": data[i * size : (i + 1) * size] for i in range(parts)}


@pytest.mark.unit
def test_the_parts_are_joined_in_order_and_checked(tmp_path: Path) -> None:
    files = split_into(WEIGHTS, 3)
    files["reconstruction_x2ct/1.0.0/otro.txt"] = b"no es una parte"
    bucket = PartsBucket(files)

    path = SplitWeightsStore(bucket, tmp_path).fetch(OBJECT, PREFIX)

    assert path == tmp_path / "reconstruction_x2ct" / "1.0.0" / "weights.pth"
    assert path.read_bytes() == WEIGHTS
    assert bucket.downloads == [f"{OBJECT}.part00", f"{OBJECT}.part01", f"{OBJECT}.part02"]


@pytest.mark.unit
def test_the_parts_are_ordered_by_number_not_by_listing(tmp_path: Path) -> None:
    files = split_into(WEIGHTS, 3)
    bucket = PartsBucket(dict(reversed(list(files.items()))))

    path = SplitWeightsStore(bucket, tmp_path).fetch(OBJECT, PREFIX)

    assert path.read_bytes() == WEIGHTS


@pytest.mark.unit
def test_the_second_fetch_uses_the_cache_without_downloading(tmp_path: Path) -> None:
    bucket = PartsBucket(split_into(WEIGHTS, 2))
    store = SplitWeightsStore(bucket, tmp_path)
    store.fetch(OBJECT, PREFIX)
    bucket.downloads.clear()

    path = store.fetch(OBJECT, PREFIX)

    assert bucket.downloads == []
    assert sha256_hex(path).startswith(PREFIX)


@pytest.mark.unit
def test_a_wrong_fingerprint_fails_and_leaves_nothing_in_the_cache(tmp_path: Path) -> None:
    corrupted = split_into(WEIGHTS, 3)
    corrupted[f"{OBJECT}.part01"] = b"\x00" * len(corrupted[f"{OBJECT}.part01"])

    with pytest.raises(WeightsIntegrityError):
        SplitWeightsStore(PartsBucket(corrupted), tmp_path).fetch(OBJECT, PREFIX)

    assert [p for p in tmp_path.rglob("*") if p.is_file()] == []


@pytest.mark.unit
def test_a_damaged_cached_file_is_downloaded_again(tmp_path: Path) -> None:
    bucket = PartsBucket(split_into(WEIGHTS, 3))
    store = SplitWeightsStore(bucket, tmp_path)
    path = store.fetch(OBJECT, PREFIX)
    path.write_bytes(b"cortado")
    bucket.downloads.clear()

    again = store.fetch(OBJECT, PREFIX)

    assert again.read_bytes() == WEIGHTS
    assert len(bucket.downloads) == 3


@pytest.mark.unit
def test_without_parts_in_the_bucket_it_fails(tmp_path: Path) -> None:
    with pytest.raises(StorageError):
        SplitWeightsStore(PartsBucket({}), tmp_path).fetch(OBJECT, PREFIX)


@pytest.mark.unit
def test_a_missing_part_is_detected(tmp_path: Path) -> None:
    files = split_into(WEIGHTS, 3)
    del files[f"{OBJECT}.part01"]

    with pytest.raises(StorageError, match="consecutivas"):
        SplitWeightsStore(PartsBucket(files), tmp_path).fetch(OBJECT, PREFIX)


@pytest.mark.unit
@pytest.mark.parametrize("bad", ["", "/abs/weights.pth", "a/../weights.pth", "a\\weights.pth"])
def test_unsafe_paths_are_rejected(tmp_path: Path, bad: str) -> None:
    with pytest.raises(StorageError):
        SplitWeightsStore(PartsBucket({}), tmp_path).fetch(bad, PREFIX)
