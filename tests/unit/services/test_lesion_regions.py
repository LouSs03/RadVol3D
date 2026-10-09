"""Pruebas de la separacion de la mascara en una region por lesion (research.md R9).

Las regiones se arman con summarize_regions, el mismo codigo que usa EN-2, para que la
prueba compruebe la correspondencia real entre el resumen y la mascara.
"""

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from radvol3d.services.meshing.lesion_regions import split_lesion_masks
from radvol3d.services.segmentation.lung_region_summary import clean_mask, summarize_regions

MM_PER_VOXEL = 2.5
EN2_MIN_VOXELS = 10
GENERATOR = Path(__file__).resolve().parents[3] / "scripts" / "generate_regression_reference.py"


def three_region_mask() -> np.ndarray:
    """Tres cubos separados, de tamanos distintos: 6, 4 y 3 voxeles de lado."""
    mask = np.zeros((32, 32, 32), dtype=np.uint8)
    mask[2:8, 2:8, 2:8] = 1
    mask[20:24, 20:24, 20:24] = 1
    mask[10:13, 25:28, 4:7] = 1
    return mask


def regions_of(mask: np.ndarray) -> list[dict]:
    probability = np.where(mask > 0, 0.8, 0.1).astype(np.float32)
    return summarize_regions(mask, probability, MM_PER_VOXEL)


@pytest.mark.unit
def test_each_region_gets_its_own_mask_in_the_order_of_the_summary() -> None:
    mask = three_region_mask()
    regions = regions_of(mask)

    masks = split_lesion_masks(mask, regions)

    assert len(masks) == 3
    assert [int(m.sum()) for m in masks] == [r["voxels"] for r in regions]
    assert [int(m.sum()) for m in masks] == [216, 64, 27]
    assert all(m.dtype == bool and m.shape == mask.shape for m in masks)
    assert masks[0][4, 4, 4] and not masks[0][21, 21, 21]
    assert masks[1][21, 21, 21]


@pytest.mark.unit
def test_the_masks_do_not_overlap_and_cover_the_whole_mask() -> None:
    mask = three_region_mask()

    masks = split_lesion_masks(mask, regions_of(mask))

    total = np.sum(masks, axis=0)
    assert total.max() == 1
    assert np.array_equal(total > 0, mask > 0)


@pytest.mark.unit
def test_no_regions_gives_no_masks() -> None:
    assert split_lesion_masks(np.zeros((4, 4, 4), dtype=np.uint8), []) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    "change", [{"voxels": 999}, {"centroid_voxel": [0, 0, 0]}]
)
def test_a_region_without_its_component_is_an_error(change: dict) -> None:
    mask = three_region_mask()
    regions = regions_of(mask)
    regions[1] = {**regions[1], **change}

    with pytest.raises(ValueError, match="region"):
        split_lesion_masks(mask, regions)


@pytest.mark.unit
def test_a_region_without_voxels_or_centroid_is_an_error() -> None:
    mask = three_region_mask()
    regions = regions_of(mask)
    del regions[0]["centroid_voxel"]

    with pytest.raises(ValueError):
        split_lesion_masks(mask, regions)


@pytest.mark.unit
def test_the_en2_region_case_splits_back_into_its_cleaned_mask() -> None:
    # El mismo caso que usa la referencia de regresion de EN-2 (caso 4), con la
    # limpieza de EN-2: min_voxeles 10, de models/metricas_test.json.
    spec = importlib.util.spec_from_file_location("generate_regression_reference", GENERATOR)
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    mask, probability = generator.build_region_summary_case()
    cleaned = clean_mask(mask > 0, EN2_MIN_VOXELS)
    regions = summarize_regions(cleaned, probability, MM_PER_VOXEL, EN2_MIN_VOXELS)

    masks = split_lesion_masks(cleaned, regions)

    assert len(masks) == len(regions) > 1
    assert np.array_equal(np.sum(masks, axis=0) > 0, cleaned > 0)
