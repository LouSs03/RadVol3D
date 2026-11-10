"""Pruebas del lector de NIfTI y del paso al convenio del sistema (modo de una radiografia)."""

import os
from pathlib import Path

import numpy as np
import pytest

from radvol3d import config
from radvol3d.domain.exceptions import RemoteReconstructionError
from radvol3d.services.reconstruction.nifti_volume import (
    read_nifti,
    rescale_window,
    to_system_volume,
)
from tests.fixtures.radiograph_files import nifti_bytes

G = config.GRID_SIZE


def marked_volume() -> np.ndarray:
    """Un volumen del servicio con una marca en el lado de la cabeza, derecha, adelante."""
    volume = np.zeros((G, G, G), dtype=np.float32)
    # eje 0 = axial (0 = cabeza), eje 1 = 0 derecha, eje 2 = 0 adelante.
    volume[2, 3, 4] = 1.0
    return volume


@pytest.mark.unit
def test_read_nifti_returns_the_same_array_in_fortran_order() -> None:
    volume = np.random.default_rng(0).random((5, 6, 7)).astype(np.float32)

    assert np.array_equal(read_nifti(nifti_bytes(volume)), volume)
    assert np.array_equal(read_nifti(nifti_bytes(volume, compress=False)), volume)


@pytest.mark.unit
def test_read_nifti_applies_the_scale_and_reads_big_endian_and_integers() -> None:
    volume = np.arange(24, dtype=np.int16).reshape(2, 3, 4)

    scaled = read_nifti(nifti_bytes(volume, datatype=4, slope=0.5, intercept=1.0))
    swapped = read_nifti(nifti_bytes(volume, datatype=4, big_endian=True))

    assert np.allclose(scaled, volume * 0.5 + 1.0)
    assert np.array_equal(swapped, volume.astype(np.float32))
    assert scaled.dtype == np.float32


@pytest.mark.unit
@pytest.mark.parametrize(
    "content",
    [b"", b"no es un nifti" * 40, b"\x1f\x8b" + b"roto" * 100],
)
def test_read_nifti_rejects_what_is_not_a_nifti(content: bytes) -> None:
    with pytest.raises(RemoteReconstructionError):
        read_nifti(content)


@pytest.mark.unit
def test_read_nifti_rejects_a_truncated_file() -> None:
    raw = nifti_bytes(np.zeros((8, 8, 8), dtype=np.float32), compress=False)

    with pytest.raises(RemoteReconstructionError, match="incompleto"):
        read_nifti(raw[:-100])


@pytest.mark.unit
def test_to_system_volume_moves_the_axes_to_right_anterior_superior() -> None:
    system = to_system_volume(marked_volume())

    # La marca estaba cerca de la cabeza, a la derecha y adelante. En el sistema el
    # eje 0 crece hacia la derecha, el 1 hacia adelante y el 2 hacia la cabeza.
    i, j, k = np.unravel_index(np.argmax(system), system.shape)
    assert (i, j, k) == (G - 1 - 3, G - 1 - 4, G - 1 - 2)


@pytest.mark.unit
def test_to_system_volume_converts_the_window_from_minus_100_900_to_minus_1000_1000() -> None:
    system = to_system_volume(marked_volume())

    # 0 en el servicio es -100 HU: 0,45 en la ventana del sistema. 1 es 900 HU: 0,95.
    assert system.dtype == np.float32
    assert system.shape == (G, G, G)
    assert float(system.min()) == pytest.approx(0.45)
    assert float(system.max()) == pytest.approx(0.95)


@pytest.mark.unit
def test_rescale_window_matches_the_formula_of_the_guide() -> None:
    values = np.array([0.0, 0.25, 1.0], dtype=np.float32)

    result = rescale_window(values, (-100.0, 900.0), (-1000.0, 1000.0))

    assert np.allclose(result, 0.45 + 0.5 * values)


@pytest.mark.unit
def test_to_system_volume_rejects_a_volume_of_another_size() -> None:
    with pytest.raises(RemoteReconstructionError, match="mide"):
        to_system_volume(np.zeros((64, 64, 64), dtype=np.float32))


@pytest.mark.unit
def test_to_system_volume_rejects_values_that_are_not_numbers() -> None:
    volume = marked_volume()
    volume[0, 0, 0] = np.nan

    with pytest.raises(RemoteReconstructionError):
        to_system_volume(volume)


EXAMPLES = Path(os.environ.get("RADVOL3D_AXON_EXAMPLES", ".cache/axon_examples"))


@pytest.mark.unit
@pytest.mark.skipif(
    not any(EXAMPLES.glob("*.nii.gz")),
    reason="Sin volumenes de ejemplo de AXON (RADVOL3D_AXON_EXAMPLES); no van al repositorio",
)
def test_the_example_volumes_have_the_liver_on_the_right_and_the_spine_behind() -> None:
    for path in sorted(EXAMPLES.glob("*.nii.gz")):
        system = to_system_volume(read_nifti(path.read_bytes()))
        half = G // 2
        lower = system[:, :, : G // 3]  # el tercio de abajo (eje 2 hacia la cabeza)
        # Higado: mas denso abajo a la derecha (eje 0 alto) que abajo a la izquierda.
        assert lower[half:].mean() > lower[:half].mean(), path.name
        # Columna: el hueso queda atras (eje 1 bajo) y no adelante.
        assert (system[:, :half] > 0.9).sum() > (system[:, half:] > 0.9).sum(), path.name
