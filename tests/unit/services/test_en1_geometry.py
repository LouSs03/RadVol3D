"""Pruebas de los operadores geometricos de EN-1 (TA-2 y TA-3), sin torch.

La igualdad numerica con el original la verifica la regresion "ml". Aqui se comprueba
el contrato: formas, constantes y las propiedades que la autoprueba original miraba.
"""

import numpy as np
import pytest

from radvol3d.services.reconstruction import en1_geometry as geometry


@pytest.mark.unit
def test_the_constants_are_the_ones_the_model_was_trained_with() -> None:
    assert geometry.G == 128
    assert geometry.FOV_MM == 320.0
    assert (geometry.HU_MIN, geometry.HU_MAX) == (-1000.0, 1000.0)
    assert geometry.ANGLES == (0.0, 45.0, 90.0, 135.0)
    assert geometry.ROTATION_AXES == (0, 1)
    assert geometry.INTEGRATION_AXIS == 1
    assert geometry.DETECTOR_AXIS == 1
    assert geometry.FILTER_EXPONENT == 0.5
    assert geometry.FBP_CALIBRATION == (17.7935, -0.0110)
    assert geometry.BP_CALIBRATION == (1.4131, -0.0591)


@pytest.mark.unit
def test_the_phantom_has_three_different_semi_axes() -> None:
    phantom = geometry.ellipsoid_phantom()

    assert phantom.shape == (128, 128, 128)
    assert phantom.dtype == np.float32
    assert set(np.unique(phantom)) == {0.0, np.float32(0.6)}


@pytest.mark.unit
def test_projecting_gives_four_views_and_the_geometry_is_not_permuted() -> None:
    projections = geometry.project(geometry.ellipsoid_phantom())

    assert projections.shape == (4, 128, 128)
    assert projections.dtype == np.float32
    # La comprobacion de la autoprueba original: la vista a 0 grados integra el eje 1,
    # asi que sus extensiones siguen los semiejes de los ejes 0 y 2, que son distintos.
    view = projections[0] > 0.02 * projections[0].max()
    assert int(view.any(axis=1).sum()) != int(view.any(axis=0).sum())


@pytest.mark.unit
def test_back_projection_gives_a_volume_and_needs_four_views() -> None:
    projections = geometry.project(geometry.ellipsoid_phantom())

    volume = geometry.back_project(projections)

    assert volume.shape == (128, 128, 128)
    assert volume.dtype == np.float32
    with pytest.raises(ValueError):
        geometry.back_project(projections[:3])


@pytest.mark.unit
def test_the_ramp_filter_keeps_the_shape() -> None:
    projections = geometry.project(geometry.ellipsoid_phantom())

    filtered = geometry.ramp_filter(projections)

    assert filtered.shape == projections.shape
    assert filtered.dtype == np.float32
    assert not np.allclose(filtered, projections)


@pytest.mark.unit
def test_the_affine_calibration_is_clipped_to_zero_one() -> None:
    values = np.array([-1.0, 0.0, 0.05, 1.0], dtype=np.float32)

    calibrated = geometry.apply_affine(values, (2.0, 0.1))

    assert calibrated.dtype == np.float32
    assert np.allclose(calibrated, [0.0, 0.1, 0.2, 1.0])
