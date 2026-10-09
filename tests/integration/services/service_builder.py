"""Arma StudyService con los almacenes reales de prueba y la fabrica con dobles.

Lo comparten las pruebas de integracion y de concurrencia de los servicios.
"""

from radvol3d.domain.enums import OrganName
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.pipeline.processing_pipeline import ProcessingPipeline
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.strategy_factory import StrategyFactory
from radvol3d.services.study_service import StudyService
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)


def build_service(
    database: Database,
    storage: ObjectStorage,
    segmentation_type: type = FakeSegmentationStrategy,
) -> tuple[StudyService, StudyMetadataStore]:
    """Servicio con los almacenes reales de prueba y la fabrica con dobles."""
    metadata = StudyMetadataStore(database, storage)
    factory = StrategyFactory(
        reconstruction_builders={"en1": FakeReconstructionStrategy},
        segmentation_builders={OrganName.LUNG: segmentation_type},
        meshing_builder=FakeMeshingStrategy,
        reconstruction_key="en1",
    )
    factory.preload()
    loader = ProjectionLoader()
    service = StudyService(
        metadata_store=metadata,
        result_store=ResultStore(database, storage),
        progress_store=ProcessingProgressStore(database),
        factory=factory,
        pipeline=ProcessingPipeline(loader),
        loader=loader,
    )
    return service, metadata
