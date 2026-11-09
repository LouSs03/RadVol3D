"""Unit checks for the LUNA16 input contract and index order."""

from unittest.mock import Mock

import numpy as np
import pytest

from radvol3d.services.reconstruction.luna16_strategy import Luna16Strategy

pytestmark = pytest.mark.unit


def test_luna16_reorders_volume_indices_without_rescaling_input():
    volume = np.zeros((128, 128, 128), dtype=np.float32)
    volume[2, 3, 4] = 0.5
    engine = Mock(return_value=volume)
    views = np.full((4, 128, 128), 0.25, dtype=np.float32)

    result = Luna16Strategy(engine).reconstruct(views)

    np.testing.assert_array_equal(engine.call_args.args[0], views)
    assert result[4, 3, 2] == 0.5
    assert result.dtype == np.float32 and result.flags.c_contiguous


@pytest.mark.parametrize("value", [-0.01, 2.0, np.nan, np.inf])
def test_luna16_rejects_invalid_projection_values_before_inference(value):
    engine = Mock()
    views = np.full((4, 128, 128), value, dtype=np.float32)
    with pytest.raises(ValueError, match="mean projections"):
        Luna16Strategy(engine).reconstruct(views)
    engine.assert_not_called()


def test_luna16_rejects_an_incomplete_set():
    engine = Mock()
    with pytest.raises(ValueError, match="four real projections"):
        Luna16Strategy(engine).reconstruct(np.zeros((3, 128, 128), dtype=np.float32))
    engine.assert_not_called()


def test_luna16_rejects_wrong_output_shape():
    engine = Mock(return_value=np.zeros((1, 128, 128), dtype=np.float32))
    with pytest.raises(RuntimeError, match="invalid normalized volume"):
        Luna16Strategy(engine).reconstruct(np.zeros((4, 128, 128), dtype=np.float32))
