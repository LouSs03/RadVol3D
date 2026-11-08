"""Segmentacion pendiente: el gancho del modo de una radiografia (requisito 8).

EN-2 se entreno con volumenes de EN-1 y no se sabe como se comporta con los del
servicio AXON, cuyos pulmones salen como zona oscura plana (el aire queda recortado en
-100 HU). Lourdes entrenara un segmentador para ellos. Mientras tanto, la etapa 3 de un
estudio de una radiografia usa esta estrategia: no detecta nada y deja el estudio
terminar en el visor con el volumen y la malla del organo, sin lesiones.

Para conectar el segmentador nuevo: crear su estrategia (con esta misma interfaz) y
registrarla en services/service_container.py, en StrategyBuilders.radiograph_segmentation.
StrategyFactory.radiograph_strategies_for la entrega en lugar de esta. La tuberia, el
servicio y la interfaz no cambian.
"""

from typing import Any

import numpy as np

from radvol3d.domain.entities import SegmentationResult
from radvol3d.domain.enums import OrganName
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy

MODEL_NAME = "segmentation_pending"
MODEL_VERSION = "0"


class PendingSegmentationStrategy(SegmentationStrategy):
    """No segmenta: devuelve una mascara vacia y un resumen sin regiones."""

    def __init__(self, organ: OrganName = OrganName.LUNG) -> None:
        self._organ = OrganName(organ)

    @property
    def model_name(self) -> str:
        return MODEL_NAME

    @property
    def model_version(self) -> str:
        return MODEL_VERSION

    def segment(self, volume: Any, study_code: str) -> SegmentationResult:
        shape = np.asarray(volume).shape
        summary = {
            "study_code": study_code,
            "organ": self._organ.value,
            "model_name": self.model_name,
            "model_version": self.model_version,
            "segmentation": "pending",
            "note": (
                "Volumen reconstruido desde una radiografia. La segmentacion de estos "
                "volumenes todavia no esta disponible: no se buscaron lesiones."
            ),
            "has_lesion": False,
            "lesion_count": 0,
            "total_volume_mm3": 0.0,
            "global_confidence": 0.0,
            "regions": [],
        }
        return SegmentationResult(
            mask=np.zeros(shape, dtype=np.uint8),
            probability=np.zeros(shape, dtype=np.float32),
            global_confidence=0.0,
            lesions=[],
            summary=summary,
        )
