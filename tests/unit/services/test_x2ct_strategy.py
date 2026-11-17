"""Pruebas de la estrategia de X2CT-GAN con un modelo falso (sin torch ni DICOM reales)."""

import json

import numpy as np
import pytest

from radvol3d.domain.exceptions import RemoteReconstructionError
from radvol3d.services.reconstruction.x2ct_strategy import (
    MODEL_NAME,
    MODEL_VERSION,
    OUTPUT_FILES,
    X2ctStrategy,
    display_voxel_mm,
    to_system_volume,
)
from tests.fixtures.radiograph_files import fake_dicom
from tests.fixtures.x2ct_fakes import GRID, FakeX2ctReconstructor, metadata


def marked_volume() -> np.ndarray:
    """Volumen de X2CT (x, y, z) en HU con un voxel marcado en cada esquina conocida."""
    volume = np.full((GRID,) * 3, -1000, np.int16)
    volume[0, 0, 0] = 1000  # izquierda de la imagen (derecha del paciente), adelante, pies
    volume[GRID - 1, 0, GRID - 1] = 0  # derecha de la imagen, adelante, cabeza
    return volume


@pytest.mark.unit
def test_the_volume_goes_to_the_system_axes_and_window() -> None:
    system = to_system_volume(marked_volume())

    assert system.shape == (GRID,) * 3
    assert system.dtype == np.float32
    # x se invierte (R), y se invierte (A), z queda (S): la esquina (0, 0, 0) de X2CT
    # pasa a (127, 127, 0), y su valor de 1000 HU a 1.0 en la ventana -1000..1000.
    assert system[GRID - 1, GRID - 1, 0] == pytest.approx(1.0)
    assert system[0, GRID - 1, GRID - 1] == pytest.approx(0.5)
    assert system[0, 0, 0] == pytest.approx(0.0)


@pytest.mark.unit
def test_a_volume_of_another_size_is_rejected() -> None:
    with pytest.raises(RemoteReconstructionError):
        to_system_volume(np.zeros((64, 64, 64), np.int16))


@pytest.mark.unit
def test_with_pixel_size_the_voxel_is_the_one_of_the_metadata() -> None:
    meta = metadata(rows=2000, columns=1600, pixel_mm=[0.2, 0.25])

    voxel, relative = display_voxel_mm(meta)

    assert voxel == pytest.approx((1600 * 0.25 / 128, 1600 * 0.25 / 128, 2000 * 0.2 / 128))
    assert relative is False


@pytest.mark.unit
def test_without_pixel_size_the_voxel_keeps_the_proportion_of_the_radiograph() -> None:
    # LIDC-IDRI-0002: 2007 filas x 1721 columnas, sin mm. X2CT pone [1, 1, 1], que la
    # estiraria a un cuadrado; aqui se conserva la proporcion original.
    meta = metadata(rows=2007, columns=1721, pixel_mm=None)

    (x, y, z), relative = display_voxel_mm(meta)

    assert relative is True
    assert (x, y, z) == pytest.approx((1721 / 128, 1721 / 128, 2007 / 128))
    assert (128 * z) / (128 * x) == pytest.approx(2007 / 1721)


@pytest.mark.unit
def test_reconstruct_study_passes_the_dicom_and_keeps_the_output_package() -> None:
    dicom = fake_dicom()
    model = FakeX2ctReconstructor(volume_hu=marked_volume())
    strategy = X2ctStrategy(model)

    result = strategy.reconstruct_study(dicom)

    assert model.inputs == [dicom]
    assert set(result.files) == set(OUTPUT_FILES)
    assert result.files["volumen.nii.gz"][:2] == b"\x1f\x8b"
    assert json.loads(result.files["metadatos.json"])["entrada"]["filas"] == 2000
    assert result.volume[GRID - 1, GRID - 1, 0] == pytest.approx(1.0)
    assert result.relative_measurements is False


@pytest.mark.unit
def test_without_pixel_size_the_relative_warning_reaches_the_view() -> None:
    # Los avisos tal como los escribe x2ct_sistema para una placa como LIDC-IDRI-0001.
    x2ct_warnings = [
        "Ventana (VOI LUT) del DICOM descartada: saturaba el 100% de la imagen.",
        "El DICOM no trae tamano de pixel: no se pueden dar medidas en mm.",
    ]
    meta = metadata(rows=2007, columns=1721, pixel_mm=None, warnings=x2ct_warnings)
    strategy = X2ctStrategy(FakeX2ctReconstructor(meta=meta))

    view = strategy.reconstruct_study(fake_dicom()).view()

    assert view["relative_measurements"] is True
    assert view["voxel_mm"] == pytest.approx([1721 / 128, 1721 / 128, 2007 / 128], abs=1e-4)
    # El aviso de "sin tamano de pixel" aparece una sola vez, el del sistema.
    assert view["warnings"] == [
        x2ct_warnings[0],
        "Sin tamaño de píxel en el DICOM: medidas relativas (sin tamaño de píxel).",
    ]
    assert view["input_size_px"] == (2007, 1721)
    assert view["model_name"] == MODEL_NAME and view["model_version"] == MODEL_VERSION


@pytest.mark.unit
def test_the_strategy_is_available_without_any_external_service() -> None:
    strategy = X2ctStrategy(FakeX2ctReconstructor())

    assert strategy.is_available() is True
    assert strategy.reconstruct(fake_dicom()).shape == (GRID,) * 3
