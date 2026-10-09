"""Pruebas de la carga de proyecciones (FR-010, FR-011; research.md R4 y R5).

El cargador lee los .npy del convenio de TA-2 y NO los reescala: EN-1 se entreno
con integrales de linea sin normalizar.
"""

import numpy as np
import pytest

from radvol3d import config
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from tests.fixtures.projection_files import four_valid_files, valid_array


@pytest.mark.unit
def test_parse_returns_one_float32_array_per_angle() -> None:
    parsed = ProjectionLoader().parse(four_valid_files(seed=3))

    assert set(parsed) == set(config.PROJECTION_ANGLES)
    for array in parsed.values():
        assert array.shape == (config.GRID_SIZE, config.GRID_SIZE)
        assert array.dtype == np.float32


@pytest.mark.unit
def test_parse_keeps_the_values_without_rescaling() -> None:
    parsed = ProjectionLoader().parse(four_valid_files(seed=3))

    for angle in config.PROJECTION_ANGLES:
        assert np.array_equal(parsed[angle], valid_array(angle, seed=3))
    # Las integrales de linea superan 1: si se normalizara, esto fallaria.
    assert max(float(a.max()) for a in parsed.values()) > 1.0


@pytest.mark.unit
def test_parse_accepts_the_files_in_any_order() -> None:
    files = list(reversed(four_valid_files(seed=5)))

    parsed = ProjectionLoader().parse(files)

    assert np.array_equal(parsed[45], valid_array(45, seed=5))


@pytest.mark.unit
def test_parse_converts_float64_to_float32() -> None:
    import io

    from radvol3d.services.pipeline.projection_loader import ProjectionFile

    files = []
    for angle in config.PROJECTION_ANGLES:
        buffer = io.BytesIO()
        np.save(buffer, valid_array(angle).astype(np.float64), allow_pickle=False)
        files.append(ProjectionFile(angle, buffer.getvalue()))

    parsed = ProjectionLoader().parse(files)

    assert all(array.dtype == np.float32 for array in parsed.values())


@pytest.mark.unit
def test_stack_orders_by_angle() -> None:
    loader = ProjectionLoader()
    parsed = loader.parse(list(reversed(four_valid_files(seed=2))))

    stacked = loader.stack(parsed)

    assert stacked.shape == (4, config.GRID_SIZE, config.GRID_SIZE)
    assert stacked.dtype == np.float32
    for position, angle in enumerate(config.PROJECTION_ANGLES):
        assert np.array_equal(stacked[position], valid_array(angle, seed=2))


# ---------------------------------------------------------------------------
# Errores (historia 2; FR-010, FR-011 y casos borde)
# ---------------------------------------------------------------------------


def files_with(angle: int, content: bytes) -> list:
    """Las cuatro proyecciones validas, con el contenido del angulo dado reemplazado."""
    from radvol3d.services.pipeline.projection_loader import ProjectionFile

    return [
        ProjectionFile(f.angle_degrees, content if f.angle_degrees == angle else f.content)
        for f in four_valid_files()
    ]


@pytest.mark.unit
def test_three_files_are_rejected_naming_the_missing_angle() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError

    files = [f for f in four_valid_files() if f.angle_degrees != 90]

    with pytest.raises(InvalidProjectionError, match="90"):
        ProjectionLoader().parse(files)


@pytest.mark.unit
def test_five_files_are_rejected() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError

    files = [*four_valid_files(), four_valid_files()[0]]

    with pytest.raises(InvalidProjectionError):
        ProjectionLoader().parse(files)


@pytest.mark.unit
def test_a_repeated_angle_is_rejected_naming_it() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from radvol3d.services.pipeline.projection_loader import ProjectionFile

    files = four_valid_files()
    files[3] = ProjectionFile(45, files[3].content)

    with pytest.raises(InvalidProjectionError, match="45"):
        ProjectionLoader().parse(files)


@pytest.mark.unit
def test_an_angle_outside_the_four_is_rejected() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from radvol3d.services.pipeline.projection_loader import ProjectionFile

    files = four_valid_files()
    files[1] = ProjectionFile(30, files[1].content)

    with pytest.raises(InvalidProjectionError):
        ProjectionLoader().parse(files)


@pytest.mark.unit
def test_a_png_is_rejected_saying_only_npy_is_accepted() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from tests.fixtures.projection_files import png_bytes

    with pytest.raises(InvalidProjectionError) as caught:
        ProjectionLoader().parse(files_with(90, png_bytes()))

    message = str(caught.value)
    assert "90" in message
    assert "solo se acepta .npy en el convenio de TA-2" in message


@pytest.mark.unit
def test_a_npy_with_python_objects_is_rejected_without_loading_it(monkeypatch) -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from tests.fixtures.projection_files import pickled_npy

    def no_pickle(*args, **kwargs):
        raise AssertionError("se intento deserializar con pickle")

    monkeypatch.setattr("pickle.loads", no_pickle)

    with pytest.raises(InvalidProjectionError, match="45"):
        ProjectionLoader().parse(files_with(45, pickled_npy()))


@pytest.mark.unit
def test_a_text_array_is_rejected() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from tests.fixtures.projection_files import npy_text_dtype

    with pytest.raises(InvalidProjectionError, match="135"):
        ProjectionLoader().parse(files_with(135, npy_text_dtype()))


@pytest.mark.unit
def test_a_wrong_shape_is_rejected_naming_the_expected_one() -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from tests.fixtures.projection_files import npy_wrong_shape

    with pytest.raises(InvalidProjectionError) as caught:
        ProjectionLoader().parse(files_with(0, npy_wrong_shape()))

    message = str(caught.value)
    assert "0" in message
    assert "(128, 128)" in message


@pytest.mark.unit
@pytest.mark.parametrize("builder", ["npy_with_nan", "npy_with_inf"])
def test_non_finite_values_are_rejected(builder: str) -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from tests.fixtures import projection_files

    content = getattr(projection_files, builder)()

    with pytest.raises(InvalidProjectionError, match="45"):
        ProjectionLoader().parse(files_with(45, content))


@pytest.mark.unit
@pytest.mark.parametrize(
    "builder", ["png_bytes", "pickled_npy", "npy_text_dtype", "npy_wrong_shape", "npy_with_nan"]
)
def test_no_message_contains_bytes_of_the_file(builder: str) -> None:
    from radvol3d.domain.exceptions import InvalidProjectionError
    from tests.fixtures import projection_files

    content = getattr(projection_files, builder)()

    with pytest.raises(InvalidProjectionError) as caught:
        ProjectionLoader().parse(files_with(90, content))

    message = str(caught.value)
    assert repr(content[:16])[2:-1] not in message  # ningun trozo de los bytes
    assert "clave" not in message  # el contenido del arreglo con objetos
    assert "90" in message
    assert len(message) < 200
