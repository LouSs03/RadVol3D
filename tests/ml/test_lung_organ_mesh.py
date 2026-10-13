"""La malla del pulmon con estudios reales: proyecciones de TA-2 y su volumen original.

Cada caso es una carpeta con <caso>_angle_{0,45,90,135}.npy (lo que sube el usuario) y
<caso>_vol.npy (la tomografia de la que salieron). Las proyecciones pasan por EN-1 y la
region del pulmon sale de la reconstruccion, como en la tuberia.

La comprobacion no usa el metodo que se prueba para definir la verdad: mira la region
sobre la tomografia ORIGINAL y exige que sea aire o pulmon ahi (por debajo del umbral
de Otsu del original). Con estos casos y 15 variantes, la region del pulmon dio 0,89 a
0,95 y la region de tejido de antes, 0,03 a 0,11 (docs/models/meshing.md).

Los datos no se versionan (.gitignore excluye *.npy). La carpeta sale de
RADVOL3D_LUNG_CASES_DIR o, si no esta definida, de src/projection. Sin casos, la prueba
se omite.
"""

import io
import os
from pathlib import Path

import numpy as np
import pytest
import trimesh
from skimage.filters import threshold_otsu

from radvol3d import config
from radvol3d.services.meshing.lung_air_region import LungAirRegion
from radvol3d.services.meshing.marching_cubes_strategy import MarchingCubesStrategy
from radvol3d.services.meshing.organ_region import LargestComponentRegion
from radvol3d.services.pipeline.projection_loader import ProjectionFile, ProjectionLoader
from radvol3d.services.reconstruction.neural_en1_strategy import NeuralEn1Strategy
from tests.ml.conftest import EN1_WEIGHTS, ROOT

CASES_DIR = Path(os.environ.get("RADVOL3D_LUNG_CASES_DIR") or ROOT / "src" / "projection")
# Fraccion minima de la region que es aire o pulmon en la tomografia original.
MIN_PURITY = 0.85
# La region del pulmon frente a la de tejido (el cuerpo) en la misma reconstruccion.
MAX_FRACTION_OF_TISSUE_REGION = 0.6


def find_cases(folder: Path) -> list[str]:
    """Los casos con sus cuatro proyecciones y su volumen original."""
    if not folder.is_dir():
        return []
    cases = []
    for volume in sorted(folder.glob("*_vol.npy")):
        case = volume.name.removesuffix("_vol.npy")
        angles = [folder / f"{case}_angle_{a}.npy" for a in config.PROJECTION_ANGLES]
        if all(path.is_file() for path in angles):
            cases.append(case)
    return cases


CASES = find_cases(CASES_DIR)


@pytest.fixture(scope="module")
def reconstruction(model_artifacts) -> NeuralEn1Strategy:
    return NeuralEn1Strategy.from_weights(model_artifacts.path(EN1_WEIGHTS))


@pytest.mark.skipif(not CASES, reason=f"No hay casos de pulmon en {CASES_DIR}.")
@pytest.mark.parametrize("case", CASES or ["sin_casos"])
def test_the_lung_mesh_of_a_real_study_is_lung_and_not_body(
    case: str, reconstruction: NeuralEn1Strategy
) -> None:
    loader = ProjectionLoader()
    files = [
        ProjectionFile(angle, (CASES_DIR / f"{case}_angle_{angle}.npy").read_bytes())
        for angle in config.PROJECTION_ANGLES
    ]
    volume = reconstruction.reconstruct(loader.stack(loader.parse(files)))
    original = np.load(CASES_DIR / f"{case}_vol.npy", allow_pickle=False).astype(np.float32)

    lungs = LungAirRegion().region(volume)
    tissue = LargestComponentRegion().region(volume)

    assert lungs.any()
    purity = float((original[lungs] <= threshold_otsu(original)).mean())
    assert purity >= MIN_PURITY, f"{case}: solo {purity:.0%} de la region es aire o pulmon"
    assert lungs.sum() <= MAX_FRACTION_OF_TISSUE_REGION * tissue.sum()
    glb = MarchingCubesStrategy(organ_region=LungAirRegion()).build_meshes(
        volume, np.zeros(volume.shape, np.uint8), []
    ).organ
    scene = trimesh.load(io.BytesIO(glb), file_type="glb")
    assert sum(len(geometry.vertices) for geometry in scene.geometry.values()) > 0
