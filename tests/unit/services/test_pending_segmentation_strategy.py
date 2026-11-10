"""Pruebas del gancho de segmentacion del modo de una radiografia (requisito 8)."""

import numpy as np
import pytest

from radvol3d.services.segmentation.pending_segmentation_strategy import (
    PendingSegmentationStrategy,
)


@pytest.mark.unit
def test_it_finds_no_lesions_and_leaves_a_valid_summary() -> None:
    strategy = PendingSegmentationStrategy()

    result = strategy.segment(np.zeros((8, 8, 8), dtype=np.float32), "rx_001")

    assert result.mask.shape == (8, 8, 8) and not result.mask.any()
    assert result.probability.dtype == np.float32
    assert result.lesions == []
    assert result.summary["regions"] == []
    assert result.summary["study_code"] == "rx_001"
    assert result.summary["organ"] == "lung"
    assert result.summary["segmentation"] == "pending"
    # El resultado se guarda con el nombre y la version del modelo (ResultStore._model_of).
    assert result.summary["model_name"] == strategy.model_name
    assert result.summary["model_version"] == strategy.model_version
