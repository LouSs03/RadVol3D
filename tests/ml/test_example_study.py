"""Estudio de ejemplo con los modelos reales y la persistencia de prueba.

Historia 5, escenarios 1 a 4; SC-003; criterio de aceptacion 2. Las proyecciones son
las del fantoma de la referencia, repartidas en cuatro .npy como las subiria un usuario.
Tarda minutos en CPU (EN-2 con TTA).
"""

import io
import json
from collections.abc import Callable

import numpy as np
import pytest
import trimesh

from radvol3d import config
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.repositories.model_repository import ModelRepository
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.marching_cubes_strategy import MarchingCubesStrategy
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionFile, ProjectionLoader
from radvol3d.services.reconstruction.neural_en1_strategy import NeuralEn1Strategy
from radvol3d.services.segmentation.lung_unet_strategy import LungUnetStrategy
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyRequest, StudyService
from tests.ml.conftest import EN1_WEIGHTS, EN2_WEIGHTS

pytestmark = pytest.mark.ml


def npy(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def test_an_example_study_produces_volume_mask_summary_and_meshes(
    model_artifacts,
    database: Database,
    object_storage: ObjectStorage,
    make_study_code: Callable[[], str],
) -> None:
    en1, en2 = model_artifacts.path(EN1_WEIGHTS), model_artifacts.path(EN2_WEIGHTS)
    factory = StrategyFactory(
        reconstruction_builders={"en1": lambda: NeuralEn1Strategy.from_weights(en1)},
        segmentation_builders={OrganName.LUNG: lambda: LungUnetStrategy.from_weights(en2)},
        meshing_builder=MarchingCubesStrategy,
        reconstruction_key="en1",
    )
    factory.preload()
    assert all(factory.availability().values())
    loader = ProjectionLoader()
    metadata = StudyMetadataStore(database, object_storage)
    service = StudyService(
        metadata_store=metadata,
        result_store=ResultStore(database, object_storage),
        progress_store=ProcessingProgressStore(database),
        factory=factory,
        pipeline=ProcessingPipeline(loader),
        loader=loader,
    )
    projections = np.load(
        model_artifacts.path("regression/en1_phantom_projections.npy"), allow_pickle=False
    )
    files = [
        ProjectionFile(angle, npy(projections[i]), f"fantoma_{angle:03d}.npy")
        for i, angle in enumerate(config.PROJECTION_ANGLES)
    ]
    code = make_study_code()

    study = service.process_study(StudyRequest(code, OrganName.LUNG, files))

    assert study.status is StudyStatus.COMPLETED
    volume = object_storage.download_array(f"{code}/volume.npy")
    assert volume.shape == (128, 128, 128) and volume.dtype == np.float32
    assert float(volume.min()) >= 0.0 and float(volume.max()) <= 1.0
    result = service.get_result(code)
    mask = object_storage.download_array(result.mask_path)
    probability = object_storage.download_array(result.probability_path)
    assert mask.dtype == np.uint8 and set(np.unique(mask)) <= {0, 1}
    assert probability.shape == mask.shape and probability.dtype == np.float32
    summary = json.loads(object_storage.download_bytes(result.summary_path))
    assert summary["study_code"] == code
    assert summary["organ"] == "lung"
    # Las regiones descartadas por la etapa de mallas quedan con has_lesion en false.
    kept = [region for region in summary["regions"] if region.get("has_lesion", True) is True]
    assert len(result.lesions) == len(kept)
    for path in (result.organ_mesh_path, result.tumor_mesh_path):
        glb = object_storage.download_bytes(path)
        assert glb.startswith(b"glTF")
        trimesh.load(io.BytesIO(glb), file_type="glb")
    with database.transaction() as connection:
        models = ModelRepository(connection)
        for name in ("reconstruction_en1", "segmentation_lung"):
            model = models.get(name, "1.0.0")
            assert model is not None
            assert model.trained_on is None

    service.delete_study(code)
