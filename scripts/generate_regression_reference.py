#!/usr/bin/env python3
"""Genera la referencia de regresion numerica de EN-1 y EN-2 con los scripts ORIGINALES.

Se corre una sola vez, en la maquina que tiene la carpeta local models/ (no versionada),
ANTES de confiar en el codigo migrado a src/radvol3d/services/. Carga los originales por
ruta, sin modificarlos, y los corre en CPU sobre entradas deterministas sin datos de
pacientes (research.md R16 de specs/002-services-pipeline).

Casos:

1. en1_phantom: EN-1 sobre las proyecciones del fantoma elipsoide de su autoprueba,
   proyectar(fantoma_elipsoide()) con sus valores por omision.
2. en2_gaussian: EN-2 sobre el volumen gaussiano de su autoprueba.
3. en2_from_en1: EN-2 sobre la salida del caso 1.
4. lung_region_summary: _limpiar y resumen_regiones originales sobre una mascara y una
   probabilidad geometricas (build_region_summary_case). Existe porque el volumen del
   caso 2 no produce lesiones: sin el, la regresion no compararia regions,
   max_diameter_mm ni la limpieza de regiones chicas. No usa torch.

Escribe:

- <output-dir>/regression/*.npy y *.json con las salidas de los casos 1 a 3 (van al
  bucket de modelos con scripts/publish_model_artifacts.py, no a git);
- tests/ml/reference/manifest.json, con el SHA-256, forma y dtype de cada objeto, la
  receta de cada entrada y el entorno (versionado);
- tests/unit/services/reference/lung_region_summary_reference.json, el caso 4
  (versionado; lo compara una prueba unitaria sin torch).

Uso (con el extra "ml" instalado):
    python scripts/generate_regression_reference.py \\
        --models-dir models \\
        --en2-weights .cache/models/segmentation_lung/1.0.0/weights.pth \\
        --output-dir .cache/models

El .pth de EN-2 es el que genera scripts/export_en2_weights.py.
"""

import argparse
import hashlib
import importlib.util
import io
import json
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPOSITORY_ROOT / "tests" / "ml" / "reference" / "manifest.json"
REGION_SUMMARY_REFERENCE = (
    REPOSITORY_ROOT / "tests" / "unit" / "services" / "reference"
    / "lung_region_summary_reference.json"
)
EN1_SOURCE = "en1_inferencia_nuevo (1).py"
EN1_WEIGHTS = "en1_pesos_liviano (2).pth"
EN2_SOURCE = "en2_inferencia.py"

# Caso 4: parametros fijos de la entrada geometrica.
REGION_CASE_SIZE = 48
REGION_CASE_MIN_VOXELS = 10
REGION_CASE_MM_PER_VOXEL = 2.5


def build_region_summary_case() -> tuple[np.ndarray, np.ndarray]:
    """Mascara uint8 y probabilidad float32 del caso 4, sin generador aleatorio.

    Tres regiones: una esfera de radio 6, un cubo de 4 voxeles de lado y un cubo de 2
    (8 voxeles, menos que min_voxeles = 10, asi que _limpiar lo descarta). La
    probabilidad dentro de cada region sigue un patron entero fijo, para que la
    confianza minima, maxima y media no sean triviales. La prueba unitaria la vuelve a
    construir con esta misma funcion.
    """
    size = REGION_CASE_SIZE
    z, y, x = np.indices((size, size, size))
    mask = np.zeros((size, size, size), dtype=np.uint8)
    mask[(z - 12) ** 2 + (y - 12) ** 2 + (x - 12) ** 2 <= 36] = 1
    mask[30:34, 30:34, 10:14] = 1
    mask[40:42, 40:42, 40:42] = 1
    pattern = ((z * 7 + y * 13 + x * 17) % 10).astype(np.float32) / 9.0
    probability = np.where(mask > 0, 0.4 + 0.5 * pattern, 0.05).astype(np.float32)
    return mask, probability


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def npy_bytes(array: np.ndarray) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, array, allow_pickle=False)
    return buffer.getvalue()


def load_original(models_dir: Path, file_name: str, module_name: str) -> ModuleType:
    """Carga un script original por ruta, sin copiarlo ni modificarlo."""
    path = models_dir / file_name
    if not path.is_file():
        raise SystemExit(f"No existe {path}: esta referencia se genera con models/ local.")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReferenceWriter:
    """Escribe los objetos de referencia y anota cada uno para el manifiesto."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def array(self, name: str, array: np.ndarray) -> dict[str, Any]:
        data = npy_bytes(array)
        return self._write(f"regression/{name}.npy", data) | {
            "shape": list(array.shape),
            "dtype": str(array.dtype),
        }

    def summary(self, name: str, summary: dict[str, Any]) -> dict[str, Any]:
        data = json.dumps(summary, ensure_ascii=False, allow_nan=False).encode("utf-8")
        return self._write(f"regression/{name}.json", data)

    def _write(self, object_path: str, data: bytes) -> dict[str, Any]:
        target = self.output_dir / object_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return {"object": object_path, "sha256": sha256_bytes(data)}


def gaussian_volume(grid: int) -> np.ndarray:
    """El volumen de la autoprueba original de EN-2, sin cambios."""
    axis = np.linspace(-1, 1, grid, dtype=np.float32)
    zz, yy, xx = np.meshgrid(axis, axis, axis, indexing="ij")
    return np.clip(0.25 + 0.5 * np.exp(-(zz**2 + yy**2 + xx**2) / 0.3), 0, 1)


def segmentation_case(
    writer: ReferenceWriter, name: str, segmenter: Any, volume: np.ndarray, recipe: str,
    input_entry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = segmenter.segmentar(volume, id_estudio=name)
    return {
        "name": name,
        "input": {"recipe": recipe, **(input_entry or {})},
        "outputs": [
            writer.array(f"{name}_mask", result["mask"]),
            writer.array(f"{name}_probability", result["probability"]),
            writer.summary(f"{name}_summary", result["summary"]),
        ],
    }


def region_summary_reference(en2: ModuleType) -> dict[str, Any]:
    mask, probability = build_region_summary_case()
    cleaned = en2._limpiar(mask > 0, REGION_CASE_MIN_VOXELS)  # noqa: SLF001 - el original
    regions = en2.resumen_regiones(
        cleaned, probability, REGION_CASE_MM_PER_VOXEL, REGION_CASE_MIN_VOXELS
    )
    return {
        "generator": "scripts/generate_regression_reference.py",
        "source": EN2_SOURCE,
        "inputs": "build_region_summary_case()",
        "min_voxels": REGION_CASE_MIN_VOXELS,
        "mm_per_voxel": REGION_CASE_MM_PER_VOXEL,
        "clean_mask_voxels": int(cleaned.sum()),
        "clean_mask_sha256": sha256_bytes(np.ascontiguousarray(cleaned, dtype=np.uint8).tobytes()),
        "regions": regions,
        "position_examples": {
            "center": en2.describir_posicion((24.0, 24.0, 24.0), (48, 48, 48)),
            "corner": en2.describir_posicion((1.0, 46.0, 30.0), (48, 48, 48)),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models-dir", required=True, type=Path)
    parser.add_argument("--en2-weights", required=True, type=Path)
    parser.add_argument("--en1-weights", type=Path, default=None)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    import scipy
    import torch

    en1 = load_original(args.models_dir, EN1_SOURCE, "en1_original")
    en2 = load_original(args.models_dir, EN2_SOURCE, "en2_original")
    writer = ReferenceWriter(args.output_dir)

    # Caso 4 primero: no usa torch y es el que compara la prueba unitaria.
    REGION_SUMMARY_REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REGION_SUMMARY_REFERENCE.write_text(
        json.dumps(region_summary_reference(en2), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    en1_weights = args.en1_weights or args.models_dir / EN1_WEIGHTS
    reconstructor = en1.ReconstructorEN1(str(en1_weights), dispositivo="cpu")
    projections = en1.proyectar(en1.fantoma_elipsoide())
    volume = reconstructor.reconstruir(projections)
    cases = [
        {
            "name": "en1_phantom",
            "input": {
                "recipe": "proyectar(fantoma_elipsoide()) con sus valores por omision",
                **writer.array("en1_phantom_projections", projections),
            },
            "outputs": [writer.array("en1_phantom_volume", volume)],
        }
    ]

    segmenter = en2.SegmentadorPulmon(str(args.en2_weights), dispositivo="cpu")
    cases.append(
        segmentation_case(
            writer, "en2_gaussian", segmenter, gaussian_volume(segmenter.rejilla),
            "volumen gaussiano de la autoprueba de en2_inferencia.py",
        )
    )
    cases.append(
        segmentation_case(
            writer, "en2_from_en1", segmenter, volume, "salida del caso en1_phantom",
            {"object": "regression/en1_phantom_volume.npy"},
        )
    )

    manifest = {
        "generated_on": datetime.now(UTC).isoformat(timespec="seconds"),
        "generator": "scripts/generate_regression_reference.py",
        "sources": {"en1": EN1_SOURCE, "en2": EN2_SOURCE},
        "weights": {
            "en1": {"file": en1_weights.name, "sha256": sha256_bytes(en1_weights.read_bytes())},
            "en2": {
                "file": args.en2_weights.name,
                "sha256": sha256_bytes(args.en2_weights.read_bytes()),
            },
        },
        "environment": {
            "torch": torch.__version__,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "device": "cpu",
        },
        "tolerance": {"mask": "exact", "volume_abs": 1e-5, "probability_abs": 1e-5},
        "cases": cases,
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Referencia escrita en {args.output_dir / 'regression'} y {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
