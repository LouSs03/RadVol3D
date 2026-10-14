"""Pruebas de la regeneracion de la malla del organo (organ_mesh_regeneration.py).

Los almacenes son dobles: ninguna prueba abre la base ni el bucket.
"""

import io
from typing import Any

import numpy as np
import pytest

from radvol3d.domain.entities import Study
from radvol3d.domain.enums import OrganName, ResultFile, StudyStatus
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy, MeshSet
from radvol3d.services.organ_mesh_regeneration import OrganMeshRegenerator, OrganMeshUpdate
from radvol3d.services.strategy_factory import StrategyFactory

VOLUME = np.linspace(0, 1, 4 * 4 * 4, dtype=np.float32).reshape(4, 4, 4)


def npy(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


class FakeMetadataStore:
    def __init__(self, studies: list[Study]) -> None:
        self.studies = studies

    def list_studies(self) -> list[Study]:
        return self.studies


class FakeResultStore:
    def __init__(self) -> None:
        self.read: list[tuple[str, ResultFile]] = []
        self.replaced: list[tuple[str, bytes]] = []

    def read_file(self, study_code: str, file: ResultFile) -> bytes:
        self.read.append((study_code, file))
        return npy(VOLUME) if file is ResultFile.VOLUME else b"glTF-vieja"

    def replace_organ_mesh(self, study_code: str, organ_mesh: bytes) -> None:
        self.replaced.append((study_code, organ_mesh))


class RecordingMeshing(MeshingStrategy):
    """Devuelve una malla con su nombre y recuerda con que la llamaron."""

    def __init__(self, name: bytes) -> None:
        self.name = name
        self.calls: list[tuple[np.ndarray, np.ndarray, list[Any]]] = []

    def build_meshes(self, volume, mask, regions) -> MeshSet:
        self.calls.append((volume, mask, list(regions)))
        return MeshSet(organ=b"glTF-" + self.name, tumor=b"glTF-tumor")


class World:
    def __init__(self, studies: list[Study] | None = None) -> None:
        self.lung = RecordingMeshing(b"pulmon")
        self.common = RecordingMeshing(b"comun")
        self.factory = StrategyFactory(
            reconstruction_builders={},
            segmentation_builders={},
            meshing_builder=lambda: self.common,
            reconstruction_key="en1",
            organ_meshing_builders={OrganName.LUNG: lambda: self.lung},
        )
        self.factory.preload()
        self.results = FakeResultStore()
        self.regenerator = OrganMeshRegenerator(
            FakeMetadataStore(studies or []), self.results, self.factory
        )


def study(code: str, status: StudyStatus, organ: OrganName = OrganName.LUNG) -> Study:
    return Study(study_code=code, organ=organ, status=status)


@pytest.mark.unit
def test_only_completed_studies_are_regenerated_in_the_order_they_came() -> None:
    world = World(
        [
            study("b", StudyStatus.COMPLETED),
            study("c", StudyStatus.PROCESSING),
            study("d", StudyStatus.FAILED),
            study("a", StudyStatus.COMPLETED),
            study("e", StudyStatus.PENDING),
        ]
    )

    codes = [s.study_code for s in world.regenerator.completed_studies()]

    assert codes == ["b", "a"]


@pytest.mark.unit
def test_build_makes_the_new_mesh_from_the_saved_volume_without_saving() -> None:
    world = World()

    update = world.regenerator.build(study("a", StudyStatus.COMPLETED))

    assert update == OrganMeshUpdate("a", OrganName.LUNG, b"glTF-vieja", b"glTF-pulmon")
    volume, mask, regions = world.lung.calls[0]
    assert np.array_equal(volume, VOLUME)
    assert mask.shape == VOLUME.shape and not mask.any()
    assert regions == []
    assert world.results.replaced == []


@pytest.mark.unit
def test_build_uses_the_meshing_the_factory_gives_to_the_organ() -> None:
    world = World()

    update = world.regenerator.build(study("h", StudyStatus.COMPLETED, OrganName.LIVER))

    assert update.current == b"glTF-comun"
    assert world.lung.calls == []


@pytest.mark.unit
def test_save_replaces_only_the_organ_mesh() -> None:
    world = World()

    world.regenerator.save("a", b"glTF-nueva")

    assert world.results.replaced == [("a", b"glTF-nueva")]
