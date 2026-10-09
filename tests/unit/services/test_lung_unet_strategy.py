"""Pruebas del envoltorio de EN-2 con un motor falso: sin torch ni pesos (FR-024, FR-025)."""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pytest

from radvol3d.domain.entities import Lesion
from radvol3d.services.segmentation.lung_region_summary import InvalidVolumeError
from radvol3d.services.segmentation.lung_unet_strategy import LungUnetStrategy

REGIONS = [
    {
        "has_lesion": True,
        "location": "medio del eje 0 · medio del eje 1 · medio del eje 2",
        "volume_mm3": 134640.62,
        "max_diameter_mm": 97.76,
        "confidence": 0.8855,
        "voxels": 8617,
        "centroid_voxel": [64, 64, 64],
        "confidence_min": 0.3002,
        "confidence_max": 0.9997,
        "region_id": 1,
    }
]


def original_summary(study_id: str | None) -> dict:
    """El resumen tal como lo arma el segmentador original (models/ejemplo_resumen.json)."""
    return {
        "study_id": study_id,
        "organ": "pulmon",
        "model_name": "segmentacion_pulmon",
        "model_version": "1.0.0",
        "threshold": 0.3,
        "mm_per_voxel": 2.5,
        "grid": 128,
        "has_lesion": True,
        "lesion_count": 1,
        "global_confidence": 0.8855,
        "total_volume_mm3": 134640.62,
        "regions": [dict(r) for r in REGIONS],
        "location_note": "posicion geometrica dentro del volumen; no es una identificacion de lobulo anatomico",
    }


class FakeEngine:
    """Imita a LungSegmenter: devuelve el diccionario del original."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.active = 0
        self.max_active = 0
        self._counter = threading.Lock()

    def segment(self, volume, study_id=None):
        with self._counter:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.005)
        with self._counter:
            self.active -= 1
        if self.error is not None:
            raise self.error
        mask = np.zeros(volume.shape, dtype=np.uint8)
        mask[60:68, 60:68, 60:68] = 1
        probability = np.where(mask > 0, 0.9, 0.0).astype(np.float32)
        return {"mask": mask, "probability": probability, "summary": original_summary(study_id)}


VOLUME = np.full((8, 8, 8), 0.5, dtype=np.float32)


@pytest.mark.unit
def test_the_summary_identifiers_are_aligned_with_the_domain() -> None:
    result = LungUnetStrategy(FakeEngine()).segment(VOLUME, "it_a")
    summary = result.summary

    assert summary["study_code"] == "it_a"
    assert "study_id" not in summary
    assert summary["organ"] == "lung"
    assert summary["model_name"] == "segmentation_lung"
    assert summary["model_version"] == "1.0.0"
    assert list(summary)[0] == "study_code"  # mismo lugar que tenia study_id


@pytest.mark.unit
def test_the_numbers_and_texts_of_the_summary_do_not_change() -> None:
    summary = LungUnetStrategy(FakeEngine()).segment(VOLUME, "it_a").summary
    original = original_summary("it_a")

    for key in ("threshold", "mm_per_voxel", "grid", "has_lesion", "lesion_count",
                "global_confidence", "total_volume_mm3", "regions", "location_note"):
        assert summary[key] == original[key]


@pytest.mark.unit
def test_each_region_becomes_a_lesion() -> None:
    result = LungUnetStrategy(FakeEngine()).segment(VOLUME, "it_a")

    assert result.lesions == [
        Lesion(
            location=REGIONS[0]["location"],
            volume_mm3=134640.62,
            confidence=0.8855,
            max_diameter_mm=97.76,
        )
    ]
    assert result.global_confidence == 0.8855
    assert result.mask.dtype == np.uint8
    assert result.probability.dtype == np.float32


@pytest.mark.unit
def test_an_invalid_volume_error_propagates() -> None:
    strategy = LungUnetStrategy(FakeEngine(InvalidVolumeError("rango fuera de [0,1]")))

    with pytest.raises(InvalidVolumeError):
        strategy.segment(VOLUME, "it_a")


@pytest.mark.unit
def test_two_threads_never_run_the_engine_at_the_same_time() -> None:
    engine = FakeEngine()
    strategy = LungUnetStrategy(engine)

    with ThreadPoolExecutor(max_workers=4) as pool:
        codes = list(pool.map(lambda n: strategy.segment(VOLUME, f"it_{n}").summary["study_code"], range(6)))

    assert engine.max_active == 1
    assert codes == [f"it_{n}" for n in range(6)]


@pytest.mark.unit
def test_the_model_name_and_version_are_the_registered_ones() -> None:
    strategy = LungUnetStrategy(FakeEngine())

    assert strategy.model_name == "segmentation_lung"
    assert strategy.model_version == "1.0.0"


@pytest.mark.unit
def test_importing_the_strategy_does_not_import_torch() -> None:
    import importlib

    already = "torch" in sys.modules
    importlib.reload(sys.modules[LungUnetStrategy.__module__])

    assert already or "torch" not in sys.modules
