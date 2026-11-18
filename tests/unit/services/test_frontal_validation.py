"""Pruebas de la validacion frontal con datos sinteticos (sin DICOM ni modelo).

La placa es un torax 2D sintetico (cuerpo claro, dos pulmones oscuros). El volumen es esa
misma placa repetida a lo largo de la profundidad, en la convencion de X2CT: su
radiografia simulada es la placa, asi que el NCC da ~1, la escala ~1,00 y el Dice 1.
"""

import io
import json

import numpy as np
import pytest
from PIL import Image

from radvol3d.services.reconstruction.frontal_validation import (
    OVERLAY_FILE,
    SIMULATED_FILE,
    VALIDATION_FILE,
    placa_from_files,
    validate,
    validate_files,
)
from radvol3d.services.reconstruction.x2ct.validacion_frontal import proyeccion_frontal
from tests.fixtures.x2ct_fakes import nifti_bytes

N = 128


def chest(lungs: int = 2) -> np.ndarray:
    """Placa sintetica 128 x 128 en [0, 1]: fondo negro, cuerpo claro y pulmones oscuros."""
    rows, cols = np.mgrid[:N, :N].astype(np.float32)
    image = np.zeros((N, N), np.float32)
    image[((cols - 64) / 56) ** 2 + ((rows - 68) / 58) ** 2 <= 1] = 0.75
    centers = [40, 88][:lungs]
    for center in centers:
        image[((cols - center) / 17) ** 2 + ((rows - 60) / 32) ** 2 <= 1] = 0.2
    image[(np.abs(cols - 64) < 5) & (rows > 20)] = 1.0  # columna
    return image


def volume_from_placa(placa: np.ndarray) -> np.ndarray:
    """Volumen en HU (x, y = AP, z) cuya proyeccion frontal es la placa."""
    frontal = placa[::-1, :].T  # (x, z): deshace el .T[::-1] de proyeccion_frontal
    hu = frontal * 2000.0 - 1000.0
    return np.repeat(hu[:, None, :], N, axis=1).astype(np.float32)


@pytest.fixture(scope="module")
def same_volume():
    placa = chest()
    return placa, validate(volume_from_placa(placa), placa)


@pytest.mark.unit
def test_the_synthetic_volume_projects_back_to_the_placa() -> None:
    placa = chest()

    np.testing.assert_allclose(proyeccion_frontal(volume_from_placa(placa)), placa, atol=1e-5)


@pytest.mark.unit
def test_a_volume_that_is_the_placa_gives_ncc_one_and_scale_one(same_volume) -> None:
    _, result = same_volume
    values = result.values

    assert values["ncc"] == pytest.approx(1.0, abs=1e-3)
    assert values["ajuste"]["escala_horizontal"] == pytest.approx(1.0, abs=0.01)
    assert values["ajuste"]["escala_vertical"] == pytest.approx(1.0, abs=0.01)
    assert values["ajuste"]["desplazamiento_horizontal_px"] == pytest.approx(0.0, abs=0.3)
    assert values["ajuste"]["desplazamiento_vertical_px"] == pytest.approx(0.0, abs=0.3)


@pytest.mark.unit
def test_the_same_lungs_give_dice_one_and_the_same_sizes(same_volume) -> None:
    _, result = same_volume
    lungs = result.values["pulmones"]

    assert lungs["disponible"] is True
    assert lungs["pulmones_encontrados"] == {"placa": 2, "reconstruccion": 2}
    assert lungs["dice_2d"] == pytest.approx(1.0)
    assert lungs["placa"] == lungs["reconstruccion"]
    assert "ancho_mm" not in lungs["placa"]
    assert result.values["medidas_en_mm"] is False


@pytest.mark.unit
def test_a_smaller_reconstruction_gives_a_scale_above_one() -> None:
    placa = chest()
    # La reconstruccion es la placa achicada un 10 % alrededor del centro.
    from scipy import ndimage

    smaller = ndimage.zoom(placa, 0.9, order=1)
    pad = (N - smaller.shape[0]) // 2
    shrunk = np.zeros_like(placa)
    shrunk[pad : pad + smaller.shape[0], pad : pad + smaller.shape[1]] = smaller

    values = validate(volume_from_placa(shrunk), placa).values

    assert values["ajuste"]["escala_horizontal"] == pytest.approx(1.11, abs=0.03)
    assert values["ajuste"]["escala_vertical"] == pytest.approx(1.11, abs=0.03)


@pytest.mark.unit
def test_with_real_mm_the_sizes_and_the_shift_are_also_in_mm() -> None:
    placa = chest()
    mm = {"vertical": 2.0, "horizontal": 3.0}

    values = validate(volume_from_placa(placa), placa, mm).values

    size = values["pulmones"]["placa"]
    assert size["ancho_mm"] == pytest.approx(size["ancho_px"] * 3.0)
    assert size["alto_mm"] == pytest.approx(size["alto_px"] * 2.0)
    assert "desplazamiento_horizontal_mm" in values["ajuste"]
    assert values["medidas_en_mm"] is True
    assert values["mm_por_pixel_128"] == mm


@pytest.mark.unit
def test_without_both_lungs_the_lungs_are_not_available_but_ncc_and_scale_are() -> None:
    placa = chest(lungs=1)

    values = validate(volume_from_placa(placa), placa).values

    assert values["pulmones"]["disponible"] is False
    assert "dice_2d" not in values["pulmones"]
    assert values["ncc"] == pytest.approx(1.0, abs=1e-3)
    assert "escala_horizontal" in values["ajuste"]


@pytest.mark.unit
def test_the_three_files_are_produced(same_volume) -> None:
    _, result = same_volume

    files = result.files()

    assert set(files) == {SIMULATED_FILE, OVERLAY_FILE, VALIDATION_FILE}
    assert json.loads(files[VALIDATION_FILE])["ncc"] == result.values["ncc"]
    assert "No valida el detalle interno" in json.loads(files[VALIDATION_FILE])["nota"]
    assert Image.open(io.BytesIO(files[SIMULATED_FILE])).size == (N, N)
    overlay = np.asarray(Image.open(io.BytesIO(files[OVERLAY_FILE])).convert("RGB"))
    assert overlay.shape == (N * 3, N * 3, 3)
    # Con las mismas mascaras, el contorno rojo (reconstruccion) tapa al verde (placa).
    assert ((overlay == [235, 40, 40]).all(axis=-1)).any()


@pytest.mark.unit
def test_the_overlay_shows_green_where_the_contours_differ() -> None:
    placa = chest()
    moved = np.roll(placa, 6, axis=0)

    overlay = np.asarray(
        Image.open(io.BytesIO(validate(volume_from_placa(moved), placa).overlay_png)).convert("RGB")
    )

    assert ((overlay == [0, 220, 0]).all(axis=-1)).any()
    assert ((overlay == [235, 40, 40]).all(axis=-1)).any()


@pytest.mark.unit
def test_the_npy_placa_is_preferred_over_the_png() -> None:
    placa = chest()
    buffer = io.BytesIO()
    np.save(buffer, placa)
    png = io.BytesIO()
    Image.fromarray(np.zeros((N, N), np.uint8)).save(png, format="PNG")

    image, source = placa_from_files(
        {"entrada_modelo_128.npy": buffer.getvalue(), "entrada_modelo_128.png": png.getvalue()}
    )

    assert source == "npy"
    np.testing.assert_array_equal(image, placa)


@pytest.mark.unit
def test_without_npy_the_png_is_used_in_zero_to_one() -> None:
    png = io.BytesIO()
    Image.fromarray(np.full((N, N), 255, np.uint8)).save(png, format="PNG")

    image, source = placa_from_files({"entrada_modelo_128.png": png.getvalue()})

    assert source == "png"
    assert image.max() == pytest.approx(1.0)


@pytest.mark.unit
def test_validate_files_reads_the_saved_package() -> None:
    placa = chest()
    buffer = io.BytesIO()
    np.save(buffer, placa)
    metadata = {"preprocesamiento": {"mm_por_pixel_128": {"vertical": 2.5, "horizontal": 2.5}}}
    files = {
        "volumen.nii.gz": nifti_bytes(np.round(volume_from_placa(placa)).astype(np.int16), (2.5,) * 3),
        "entrada_modelo_128.npy": buffer.getvalue(),
        "metadatos.json": json.dumps(metadata).encode(),
    }

    values = validate_files(files).values

    assert values["placa_usada"] == "npy"
    assert values["ncc"] == pytest.approx(1.0, abs=1e-3)
    assert values["medidas_en_mm"] is True
