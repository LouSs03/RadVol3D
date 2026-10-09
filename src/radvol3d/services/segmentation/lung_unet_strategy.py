"""Segmentacion de tumor de pulmon con la U-Net 3D residual EN-2.

Los pesos viven en el bucket de modelos y los baja service_container al arrancar.
Metricas y referencia en docs/models/segmentation_lung_en2.md.

La estrategia envuelve el segmentador migrado sin cambiar su logica (FR-023a). Lo unico
que hace sobre su salida es alinear los identificadores de texto del resumen con el
dominio (FR-025): study_id pasa a study_code, el organo a "lung" y el nombre y la
version del modelo a los registrados en la tabla model. Los numeros no se tocan. Asi
funciona igual con el .pth generado por scripts/export_en2_weights.py y con el original.

Este modulo no importa torch en su nivel superior: from_weights lo importa recien al
construir el motor.
"""

import threading
from pathlib import Path
from typing import Any

from radvol3d.domain.entities import Lesion, SegmentationResult
from radvol3d.domain.enums import OrganName
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy


class LungUnetStrategy(SegmentationStrategy):
    """Segmenta tumor pulmonar. Un candado serializa la inferencia (research.md R13)."""

    def __init__(self, engine: Any) -> None:
        self._engine = engine
        self._lock = threading.Lock()

    @classmethod
    def from_weights(cls, weights_path: str | Path) -> "LungUnetStrategy":
        """Carga los pesos una sola vez. Importa torch solo aqui."""
        from radvol3d.services.segmentation.lung_segmenter import LungSegmenter

        return cls(LungSegmenter(str(weights_path), device="cpu"))

    def segment(self, volume: Any, study_code: str) -> SegmentationResult:
        # El segmentador valida que el volumen venga en [0,1] con la ventana HU de la
        # reconstruccion; si no, lanza InvalidVolumeError y la etapa 3 falla.
        with self._lock:
            output = self._engine.segment(volume)
        summary = self._aligned_summary(output["summary"], study_code)
        lesions = [
            Lesion(
                location=region["location"],
                volume_mm3=region["volume_mm3"],
                confidence=region["confidence"],
                max_diameter_mm=region.get("max_diameter_mm"),
            )
            for region in summary["regions"]
            if region.get("has_lesion", True) is True
        ]
        return SegmentationResult(
            mask=output["mask"],
            probability=output["probability"],
            global_confidence=summary["global_confidence"],
            lesions=lesions,
            summary=summary,
        )

    def _aligned_summary(self, original: dict, study_code: str) -> dict:
        """El mismo resumen, en el mismo orden, con los identificadores del dominio."""
        replacements = {
            "organ": OrganName.LUNG.value,
            "model_name": self.model_name,
            "model_version": self.model_version,
        }
        aligned = {}
        for key, value in original.items():
            if key == "study_id":
                aligned["study_code"] = study_code
            else:
                aligned[key] = replacements.get(key, value)
        aligned.setdefault("study_code", study_code)
        return aligned

    @property
    def model_name(self) -> str:
        return "segmentation_lung"

    @property
    def model_version(self) -> str:
        return "1.0.0"
