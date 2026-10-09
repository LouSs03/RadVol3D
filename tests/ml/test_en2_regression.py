"""Regresion numerica de EN-2 y alineacion del resumen (FR-025, FR-034).

Cada caso corre el segmentador migrado una sola vez (tarda minutos en CPU): un motor
que guarda la salida cruda permite comparar el resumen sin alinear con la referencia y,
con la misma corrida, el resumen alineado que entrega la estrategia.

LungSegmenter usa torch: se importa dentro de la fixture, no al nivel del modulo, para
que la coleccion de pytest no falle donde torch no esta instalado (el CI).
"""

import importlib.util
import json
from typing import Any

import numpy as np
import pytest

from radvol3d.services.segmentation.lung_unet_strategy import LungUnetStrategy
from tests.ml.conftest import EN2_WEIGHTS, ROOT

pytestmark = pytest.mark.ml

TOLERANCE = 1e-5
IDENTIFIERS = {"study_id", "study_code", "organ", "model_name", "model_version"}


def gaussian_volume(grid: int) -> np.ndarray:
    path = ROOT / "scripts" / "generate_regression_reference.py"
    spec = importlib.util.spec_from_file_location("generate_regression_reference", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.gaussian_volume(grid)


class RecordingEngine:
    """Envuelve al segmentador real y guarda su salida cruda, con el id de la referencia."""

    def __init__(self, segmenter: Any, study_id: str) -> None:
        self.segmenter = segmenter
        self.study_id = study_id
        self.raw: dict | None = None

    def segment(self, volume):
        self.raw = self.segmenter.segment(volume, study_id=self.study_id)
        return self.raw


@pytest.fixture(scope="module")
def segmenter(model_artifacts) -> Any:
    from radvol3d.services.segmentation.lung_segmenter import LungSegmenter

    return LungSegmenter(str(model_artifacts.path(EN2_WEIGHTS)))


@pytest.mark.parametrize("case", ["en2_gaussian", "en2_from_en1"])
def test_en2_matches_the_reference_and_the_strategy_aligns_the_summary(
    model_artifacts, segmenter: Any, case: str
) -> None:
    if case == "en2_gaussian":
        volume = gaussian_volume(segmenter.grid)
    else:
        volume = np.load(
            model_artifacts.path("regression/en1_phantom_volume.npy"), allow_pickle=False
        )
    expected_mask = np.load(model_artifacts.path(f"regression/{case}_mask.npy"))
    expected_probability = np.load(model_artifacts.path(f"regression/{case}_probability.npy"))
    expected_summary = json.loads(
        model_artifacts.path(f"regression/{case}_summary.json").read_text(encoding="utf-8")
    )
    engine = RecordingEngine(segmenter, study_id=case)

    result = LungUnetStrategy(engine).segment(volume, "it_ml")

    raw = engine.raw
    assert np.array_equal(raw["mask"], expected_mask), model_artifacts.environment_note()
    difference = float(np.abs(raw["probability"] - expected_probability).max())
    assert difference <= TOLERANCE, (
        f"EN-2 difiere en {difference:.3e}; " + model_artifacts.environment_note()
    )
    assert json.loads(json.dumps(raw["summary"])) == expected_summary

    aligned = result.summary
    assert aligned["study_code"] == "it_ml"
    assert aligned["organ"] == "lung"
    assert aligned["model_name"] == "segmentation_lung"
    for key, value in expected_summary.items():
        if key not in IDENTIFIERS:
            assert json.loads(json.dumps(aligned[key])) == value, key
    assert len(result.lesions) == expected_summary["lesion_count"]
