"""Sube los pesos de X2CT-GAN (1 vista) al bucket de modelos, partidos en trozos.

El plan gratuito de Supabase no acepta archivos de mas de 50 MB y los pesos pesan
118 MB: se suben en partes de menos de 45 MB, sin convertirlos ni modificarlos.

    reconstruction_x2ct/1.0.0/weights.pth.part00
    reconstruction_x2ct/1.0.0/weights.pth.part01
    reconstruction_x2ct/1.0.0/weights.pth.part02

El backend las baja, las une y comprueba la huella (persistence/split_weights_store.py).

No reemplaza nada: si ya hay alguna parte en esa ruta, se detiene sin subir. Antes de
subir comprueba que la huella del archivo local sea la esperada.

Uso:
    python scripts/publish_x2ct_weights.py --weights docs/x2ct/30_net_G.pth
    # despues, en el .env: X2CT_WEIGHTS_OBJECT=reconstruction_x2ct/1.0.0/weights.pth
"""

import argparse
import hashlib
import math
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from radvol3d.persistence.object_storage import (  # noqa: E402 - despues de ajustar sys.path
    CONTENT_TYPE_ARRAY,
    ObjectStorage,
)
from radvol3d.persistence.settings import ModelSettings, Settings  # noqa: E402
from radvol3d.services.reconstruction.x2ct_strategy import (  # noqa: E402
    X2CT_WEIGHTS_OBJECT,
    X2CT_WEIGHTS_SHA256_PREFIX,
)

MAX_PART_BYTES = 45 * 1000 * 1000


def split(data: bytes, max_part_bytes: int = MAX_PART_BYTES) -> list[bytes]:
    """Trozos de igual tamano (el ultimo puede ser menor), todos de menos del maximo."""
    count = max(1, math.ceil(len(data) / max_part_bytes))
    size = math.ceil(len(data) / count)
    return [data[start : start + size] for start in range(0, len(data), size)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--weights", required=True, type=Path, help="El 30_net_G.pth local")
    parser.add_argument("--env-file", type=Path, default=REPOSITORY_ROOT / ".env")
    parser.add_argument("--object", default=X2CT_WEIGHTS_OBJECT)
    args = parser.parse_args(argv)

    data = args.weights.read_bytes()
    fingerprint = hashlib.sha256(data).hexdigest()
    if not fingerprint.startswith(X2CT_WEIGHTS_SHA256_PREFIX):
        print(f"La huella del archivo ({fingerprint[:12]}) no es la esperada.", file=sys.stderr)
        return 1

    settings = Settings(_env_file=args.env_file)
    bucket = ModelSettings(_env_file=args.env_file).model_bucket
    if not bucket:
        print("Falta MODEL_BUCKET en el archivo de entorno.", file=sys.stderr)
        return 1
    storage = ObjectStorage.from_settings(settings, bucket=bucket)

    chunks = split(data)
    paths = [f"{args.object}.part{index:02d}" for index in range(len(chunks))]
    occupied = [path for path in paths if storage.exists(path)]
    if occupied:
        print("Ya hay partes en el bucket; no se reemplaza nada: " + ", ".join(occupied))
        return 1
    for path, chunk in zip(paths, chunks, strict=True):
        storage.upload_bytes(path, chunk, CONTENT_TYPE_ARRAY)
        print(f"subido {path} ({len(chunk) / 1e6:.1f} MB)")
    print(f"SHA-256: {fingerprint[:12]}")
    print(f"X2CT_WEIGHTS_OBJECT={args.object}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
