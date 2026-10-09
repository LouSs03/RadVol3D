"""Baja los pesos de los modelos del bucket de modelos y los guarda en una cache local.

Los pesos no viven en git. Al arrancar se piden una sola vez: si ya estan en la
cache, no se vuelven a bajar. La descarga se escribe primero en un temporal de la
misma carpeta y despues se renombra, para que una descarga cortada nunca deje un
archivo a medias que parezca valido (research.md R10 de la funcionalidad 002).
"""

import os
import tempfile
from pathlib import Path, PurePosixPath

from radvol3d.domain.exceptions import StorageError
from radvol3d.persistence.object_storage import ObjectStorage


class ModelWeightsStore:
    """Entrega la ruta local de un archivo de pesos, bajandolo si hace falta."""

    def __init__(self, storage: ObjectStorage, cache_dir: Path) -> None:
        self._storage = storage
        self._cache_dir = Path(cache_dir)

    def fetch(self, object_path: str) -> Path:
        """Devuelve la ruta local del objeto. Lo baja del bucket solo la primera vez."""
        local_path = self._cache_dir.joinpath(*self._safe_parts(object_path))
        if local_path.is_file():
            return local_path
        data = self._storage.download_bytes(object_path)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=local_path.parent, suffix=".partial")
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
            os.replace(temporary, local_path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
        return local_path

    @staticmethod
    def _safe_parts(object_path: str) -> tuple[str, ...]:
        """Partes de la ruta, sin '..', barra invertida ni ruta absoluta."""
        if not object_path or "\\" in object_path or object_path.startswith("/"):
            raise StorageError("La ruta del archivo de pesos no es valida.")
        parts = PurePosixPath(object_path).parts
        if any(part in ("..", ".") for part in parts):
            raise StorageError("La ruta del archivo de pesos no es valida.")
        return parts
