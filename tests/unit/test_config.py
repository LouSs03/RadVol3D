"""Comprueba las constantes de config que agrega la funcionalidad 004."""

import pytest

from radvol3d import config


@pytest.mark.unit
def test_a_projection_file_can_weigh_up_to_one_mebibyte() -> None:
    assert config.MAX_PROJECTION_BYTES == 1_048_576


@pytest.mark.unit
def test_the_limit_leaves_room_for_a_float64_projection() -> None:
    # 128 x 128 x 8 bytes mas la cabecera de 128 bytes de un .npy.
    assert config.MAX_PROJECTION_BYTES > 128 * 128 * 8 + 128
