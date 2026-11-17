"""Pesos guardados en partes en el bucket de modelos: los baja, los une y los verifica.

El plan gratuito de Supabase no acepta archivos de mas de 50 MB. Los pesos de X2CT-GAN
pesan 118 MB, asi que viven en el bucket partidos en trozos de menos de 45 MB:

    reconstruction_x2ct/1.0.0/weights.pth.part00
    reconstruction_x2ct/1.0.0/weights.pth.part01
    reconstruction_x2ct/1.0.0/weights.pth.part02

(los sube scripts/publish_x2ct_weights.py). fetch() baja las partes en orden, las une
en un temporal de la cache, comprueba la huella SHA-256 y solo entonces lo renombra a
<cache>/reconstruction_x2ct/1.0.0/weights.pth. Si la huella no coincide, borra el
temporal y falla: nunca queda en la cache un archivo de pesos que no sea el esperado.
En los arranques siguientes usa el archivo de la cache, despues de volver a comprobar
su huella (unos segundos con 118 MB).

Los pesos no se convierten ni se recortan: el archivo unido es byte a byte el original.
"""

import hashlib
import os
import re
import tempfile
from pathlib import Path, PurePosixPath

from radvol3d.domain.exceptions import StorageError
from radvol3d.persistence.object_storage import ObjectStorage

PART_SUFFIX = re.compile(r"\.part(\d{2})")
READ_CHUNK_BYTES = 1 << 20


class WeightsIntegrityError(StorageError):
    """El archivo de pesos unido no tiene la huella esperada."""


class SplitWeightsStore:
    """Entrega la ruta local de unos pesos guardados en partes, ya verificados."""

    def __init__(self, storage: ObjectStorage, cache_dir: Path) -> None:
        self._storage = storage
        self._cache_dir = Path(cache_dir)

    def fetch(self, object_path: str, sha256_prefix: str) -> Path:
        """Ruta local del archivo unido. Lo baja y lo une solo si no esta en la cache.

        object_path es la ruta del archivo entero (sin .partNN). sha256_prefix son los
        primeros caracteres de su SHA-256: si no coinciden, lanza WeightsIntegrityError.
        """
        parts = _safe_parts(object_path)
        local_path = self._cache_dir.joinpath(*parts)
        if local_path.is_file() and sha256_hex(local_path).startswith(sha256_prefix):
            return local_path
        part_paths = self.part_paths(object_path)
        if not part_paths:
            raise StorageError(f"No hay partes de '{object_path}' en el bucket de modelos.")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=local_path.parent, suffix=".partial")
        try:
            digest = hashlib.sha256()
            with os.fdopen(descriptor, "wb") as handle:
                for part_path in part_paths:
                    data = self._storage.download_bytes(part_path)
                    digest.update(data)
                    handle.write(data)
            if not digest.hexdigest().startswith(sha256_prefix):
                raise WeightsIntegrityError(
                    f"La huella de '{object_path}' no es la esperada ({sha256_prefix})."
                )
            os.replace(temporary, local_path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return local_path

    def part_paths(self, object_path: str) -> list[str]:
        """Las rutas de las partes en el bucket, en orden (.part00, .part01, ...)."""
        parts = _safe_parts(object_path)
        folder = "/".join(parts[:-1])
        name = parts[-1]
        numbered = []
        for entry in self._storage.list_names(folder):
            if not entry.startswith(name):
                continue
            match = PART_SUFFIX.fullmatch(entry[len(name) :])
            if match:
                numbered.append((int(match.group(1)), f"{folder}/{entry}" if folder else entry))
        numbers = [number for number, _ in sorted(numbered)]
        if numbers != list(range(len(numbers))):
            raise StorageError(f"Las partes de '{object_path}' no son consecutivas: {numbers}.")
        return [path for _, path in sorted(numbered)]


def sha256_hex(path: Path) -> str:
    """SHA-256 de un archivo, leido por bloques."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(READ_CHUNK_BYTES), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_parts(object_path: str) -> tuple[str, ...]:
    """Partes de la ruta, sin '..', barra invertida ni ruta absoluta."""
    if not object_path or "\\" in object_path or object_path.startswith("/"):
        raise StorageError("La ruta del archivo de pesos no es valida.")
    parts = PurePosixPath(object_path).parts
    if any(part in ("..", ".") for part in parts):
        raise StorageError("La ruta del archivo de pesos no es valida.")
    return parts
