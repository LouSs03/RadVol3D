"""Dos estudios a la vez no mezclan sus resultados (FR-020, SC-005, SC-006).

Corre StudyService con los dobles y la persistencia de prueba. Los dos estudios
comparten las mismas instancias de estrategia, como en el servidor real.
"""

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyRequest, StudyService
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)
from tests.fixtures.projection_files import four_valid_files

pytestmark = pytest.mark.concurrency

REPETITIONS = 20
SEEDS = (101, 202)


class CountingBuilder:
    def __init__(self, strategy_type: type) -> None:
        self.strategy_type = strategy_type
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.strategy_type()


def what_was_saved(storage: ObjectStorage, code: str) -> tuple[np.ndarray, dict]:
    """El volumen y el resumen guardados, sin el codigo del estudio (que si cambia)."""
    volume = storage.download_array(f"{code}/volume.npy")
    summary = json.loads(storage.download_bytes(f"{code}/segmentation/summary.json"))
    summary.pop("study_code")
    return volume, summary


def test_two_studies_at_once_get_the_same_results_as_one_by_one(
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    builders = [
        CountingBuilder(FakeReconstructionStrategy),
        CountingBuilder(FakeSegmentationStrategy),
        CountingBuilder(FakeMeshingStrategy),
    ]
    factory = StrategyFactory(
        reconstruction_builders={"en1": builders[0]},
        segmentation_builders={OrganName.LUNG: builders[1]},
        meshing_builder=builders[2],
        reconstruction_key="en1",
    )
    factory.preload()
    loader = ProjectionLoader()
    service = StudyService(
        metadata_store=StudyMetadataStore(database, object_storage),
        result_store=ResultStore(database, object_storage),
        progress_store=ProcessingProgressStore(database),
        factory=factory,
        pipeline=ProcessingPipeline(loader),
        loader=loader,
    )

    def process(seed: int) -> str:
        code = make_study_code()
        study = service.process_study(
            StudyRequest(code, OrganName.LUNG, four_valid_files(seed=seed))
        )
        assert study.status is StudyStatus.COMPLETED
        return code

    # Referencia: cada estudio procesado solo.
    expected = {}
    for seed in SEEDS:
        code = process(seed)
        expected[seed] = what_was_saved(object_storage, code)
        service.delete_study(code)
    assert not np.array_equal(expected[SEEDS[0]][0], expected[SEEDS[1]][0])

    with ThreadPoolExecutor(max_workers=2) as pool:
        for _ in range(REPETITIONS):
            codes = dict(zip(SEEDS, pool.map(process, SEEDS), strict=True))
            for seed, code in codes.items():
                volume, summary = what_was_saved(object_storage, code)
                assert np.array_equal(volume, expected[seed][0]), (seed, code)
                assert summary == expected[seed][1]
            for code in codes.values():
                service.delete_study(code)

    assert [b.calls for b in builders] == [1, 1, 1]
