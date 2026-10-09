#!/usr/bin/env python3
"""Sube los pesos y la referencia de regresion al bucket de modelos (contracts/model_artifacts.md).

Rutas en el bucket (MODEL_BUCKET):

    reconstruction_en1/1.0.0/weights.pth   <- --en1-weights, sin cambios
    segmentation_lung/1.0.0/weights.pth    <- --en2-weights (de scripts/export_en2_weights.py)
    regression/<archivo>                   <- cada archivo de --regression-dir

Lee las credenciales de Supabase y MODEL_BUCKET del archivo indicado con --env-file
(por omision .env). Para el proyecto de prueba, --env-file .env.test. No imprime claves
ni URLs firmadas: solo las rutas dentro del bucket. Subir a una ruta ocupada reemplaza
el archivo.

Despues de subir, escribe en el .env usado EN1_WEIGHTS_OBJECT y EN2_WEIGHTS_OBJECT con
las dos primeras rutas (a mano: el script no modifica archivos de configuracion).

Uso:
    python scripts/publish_model_artifacts.py --env-file .env.test \\
        --en1-weights "models/en1_pesos_liviano (2).pth" \\
        --en2-weights .cache/models/segmentation_lung/1.0.0/weights.pth \\
        --regression-dir .cache/models/regression
"""

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from radvol3d.persistence.object_storage import (  # noqa: E402 - despues de ajustar sys.path
    CONTENT_TYPE_ARRAY,
    CONTENT_TYPE_JSON,
    ObjectStorage,
)
from radvol3d.persistence.settings import ModelSettings, Settings  # noqa: E402

EN1_OBJECT = "reconstruction_en1/1.0.0/weights.pth"
EN2_OBJECT = "segmentation_lung/1.0.0/weights.pth"


def artifacts_to_publish(
    en1_weights: Path, en2_weights: Path, regression_dir: Path
) -> list[tuple[Path, str, str]]:
    """(archivo local, ruta en el bucket, tipo de contenido) de cada artefacto."""
    items = [
        (en1_weights, EN1_OBJECT, CONTENT_TYPE_ARRAY),
        (en2_weights, EN2_OBJECT, CONTENT_TYPE_ARRAY),
    ]
    for path in sorted(regression_dir.glob("*")):
        if path.is_file():
            content_type = CONTENT_TYPE_JSON if path.suffix == ".json" else CONTENT_TYPE_ARRAY
            items.append((path, f"regression/{path.name}", content_type))
    return items


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=REPOSITORY_ROOT / ".env")
    parser.add_argument("--en1-weights", required=True, type=Path)
    parser.add_argument("--en2-weights", required=True, type=Path)
    parser.add_argument("--regression-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    settings = Settings(_env_file=args.env_file)
    model_settings = ModelSettings(_env_file=args.env_file)
    if not model_settings.model_bucket:
        print(f"Falta MODEL_BUCKET en {args.env_file}.", file=sys.stderr)
        return 1
    storage = ObjectStorage.from_settings(settings, bucket=model_settings.model_bucket)

    items = artifacts_to_publish(args.en1_weights, args.en2_weights, args.regression_dir)
    missing = [str(local) for local, _, _ in items if not local.is_file()]
    if missing:
        print("Faltan archivos locales: " + ", ".join(missing), file=sys.stderr)
        return 1
    for local, object_path, content_type in items:
        storage.upload_bytes(object_path, local.read_bytes(), content_type)
        print(f"subido {object_path}")
    print(f"EN1_WEIGHTS_OBJECT={EN1_OBJECT}")
    print(f"EN2_WEIGHTS_OBJECT={EN2_OBJECT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
