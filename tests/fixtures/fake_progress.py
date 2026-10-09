"""Doble del puerto PipelineProgress.

Anota cada llamada como una tupla en events, en orden. Con eso las pruebas de la
tuberia comprueban la secuencia exacta de etapas sin base de datos ni bucket.
"""

import threading

import numpy as np

from radvol3d.domain.entities import SegmentationResult
from radvol3d.domain.enums import StageNumber
from radvol3d.services.meshing.meshing_strategy import MeshSet


class RecordingProgress:
    """Guarda los eventos y lo que se le pide guardar. Es seguro entre hilos.

    fail_on es una tupla (evento, codigo) o (evento, codigo, etapa): esa llamada
    lanza RuntimeError("fallo preparado") y no se anota. Los eventos son started,
    completed, failed, save_volume y save_result.
    """

    def __init__(self, fail_on: tuple | None = None) -> None:
        self.events: list[tuple] = []
        self.volumes: dict[str, np.ndarray] = {}
        self.results: dict[str, tuple[SegmentationResult, MeshSet]] = {}
        self._fail_on = fail_on
        self._lock = threading.Lock()

    def _record(self, event: tuple) -> None:
        if self._fail_on is not None and event[: len(self._fail_on)] == self._fail_on:
            raise RuntimeError("fallo preparado")
        with self._lock:
            self.events.append(event)

    def stage_started(self, study_code: str, stage: StageNumber) -> None:
        self._record(("started", study_code, StageNumber(stage).value))

    def stage_completed(
        self,
        study_code: str,
        stage: StageNumber,
        model_name: str | None = None,
        model_version: str | None = None,
    ) -> None:
        self._record(
            ("completed", study_code, StageNumber(stage).value, model_name, model_version)
        )

    def stage_failed(self, study_code: str, stage: StageNumber) -> None:
        self._record(("failed", study_code, StageNumber(stage).value))

    def save_volume(self, study_code: str, volume: np.ndarray) -> None:
        self._record(("save_volume", study_code))
        with self._lock:
            self.volumes[study_code] = volume

    def save_result(
        self, study_code: str, segmentation: SegmentationResult, meshes: MeshSet
    ) -> None:
        self._record(("save_result", study_code))
        with self._lock:
            self.results[study_code] = (segmentation, meshes)
