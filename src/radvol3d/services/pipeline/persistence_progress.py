"""Implementacion del puerto PipelineProgress sobre los almacenes de la persistencia.

Es la unica pieza de la tuberia que sabe que existe la persistencia. La tuberia
solo conoce el puerto.
"""

from numpy import ndarray

from radvol3d.domain.entities import SegmentationResult
from radvol3d.domain.enums import StageNumber
from radvol3d.persistence.processing_progress_store import ProcessingProgressStore
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.meshing.meshing_strategy import MeshSet


class PersistenceProgress:
    """Traduce cada aviso de la tuberia a la llamada del almacen que corresponde."""

    def __init__(
        self,
        progress_store: ProcessingProgressStore,
        metadata_store: StudyMetadataStore,
        result_store: ResultStore,
    ) -> None:
        self._progress_store = progress_store
        self._metadata_store = metadata_store
        self._result_store = result_store

    def stage_started(self, study_code: str, stage: StageNumber) -> None:
        self._progress_store.start_stage(study_code, stage)

    def stage_completed(
        self,
        study_code: str,
        stage: StageNumber,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        self._progress_store.complete_stage(study_code, stage, model_name, model_version)

    def stage_failed(self, study_code: str, stage: StageNumber) -> None:
        self._progress_store.fail_from_stage(study_code, stage)

    def save_volume(self, study_code: str, volume: ndarray) -> None:
        self._metadata_store.save_volume(study_code, volume)

    def save_result(
        self, study_code: str, segmentation: SegmentationResult, meshes: MeshSet
    ) -> None:
        self._result_store.save_result(
            study_code,
            segmentation.mask,
            segmentation.probability,
            segmentation.summary,
            meshes.organ,
            meshes.tumor,
        )
