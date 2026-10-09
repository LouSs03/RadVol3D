"""Pruebas del resumen por regiones de EN-2, sin torch.

La comparacion exacta con el original usa el caso 4 de la referencia, que genera
scripts/generate_regression_reference.py con la carpeta local models/. Mientras esa
referencia no exista, esa prueba se omite y lo dice. Las demas comprueban el contrato.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from radvol3d.services.segmentation import lung_region_summary as summary

ROOT = Path(__file__).resolve().parents[3]
REFERENCE = ROOT / "tests" / "unit" / "services" / "reference" / "lung_region_summary_reference.json"
SCRIPT = ROOT / "scripts" / "generate_regression_reference.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("generate_regression_reference", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_the_migrated_summary_matches_the_original_reference() -> None:
    if not REFERENCE.is_file():
        pytest.skip(
            "Falta la referencia del caso 4: corre scripts/generate_regression_reference.py "
            "en la maquina que tiene models/."
        )
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    mask, probability = load_generator().build_region_summary_case()

    cleaned = summary.clean_mask(mask > 0, reference["min_voxels"])
    regions = summary.summarize_regions(
        cleaned, probability, reference["mm_per_voxel"], reference["min_voxels"]
    )

    assert int(cleaned.sum()) == reference["clean_mask_voxels"]
    digest = hashlib.sha256(np.ascontiguousarray(cleaned, dtype=np.uint8).tobytes()).hexdigest()
    assert digest == reference["clean_mask_sha256"]
    assert json.loads(json.dumps(regions)) == reference["regions"]
    examples = reference["position_examples"]
    assert summary.describe_position((24.0, 24.0, 24.0), (48, 48, 48)) == examples["center"]
    assert summary.describe_position((1.0, 46.0, 30.0), (48, 48, 48)) == examples["corner"]


@pytest.mark.unit
def test_small_regions_are_cleaned_and_the_rest_summarized_largest_first() -> None:
    mask, probability = load_generator().build_region_summary_case()

    cleaned = summary.clean_mask(mask > 0, 10)
    regions = summary.summarize_regions(cleaned, probability, 2.5, 10)

    assert cleaned.dtype == np.uint8
    assert int(cleaned.sum()) == int(mask.sum()) - 8  # el cubo de 2x2x2 se descarta
    assert [r["region_id"] for r in regions] == [1, 2]
    assert regions[0]["volume_mm3"] > regions[1]["volume_mm3"]
    for region in regions:
        assert region["has_lesion"] is True
        assert region["volume_mm3"] == round(region["voxels"] * 2.5**3, 2)
        assert region["confidence_min"] <= region["confidence"] <= region["confidence_max"]
        assert region["max_diameter_mm"] > 0
        assert set(region) == {
            "has_lesion", "location", "volume_mm3", "max_diameter_mm", "confidence",
            "voxels", "centroid_voxel", "confidence_min", "confidence_max", "region_id",
        }


@pytest.mark.unit
def test_an_empty_mask_has_no_regions() -> None:
    empty = np.zeros((16, 16, 16), dtype=np.uint8)

    assert summary.summarize_regions(empty, np.zeros((16, 16, 16), np.float32), 2.5, 10) == []
    assert summary.clean_mask(empty > 0, 10).sum() == 0


@pytest.mark.unit
def test_positions_are_described_in_spanish_by_thirds() -> None:
    assert (
        summary.describe_position((64.0, 64.0, 64.0), (128, 128, 128))
        == "medio del eje 0 · medio del eje 1 · medio del eje 2"
    )
    assert (
        summary.describe_position((0.0, 127.0, 10.0), (128, 128, 128))
        == "inicio del eje 0 · final del eje 1 · inicio del eje 2"
    )


@pytest.mark.unit
def test_patch_positions_and_the_gaussian_map() -> None:
    assert summary.patch_positions(128, 96, 0.5) == [0, 32]
    assert summary.patch_positions(64, 96, 0.5) == [0]
    weights = summary.gaussian_weight_map(96)
    assert weights.shape == (96, 96, 96)
    assert weights.dtype == np.float32
    assert float(weights.max()) == 1.0


@pytest.mark.unit
def test_invalid_volume_error_is_a_value_error() -> None:
    assert issubclass(summary.InvalidVolumeError, ValueError)
