"""Doble del bucket de Supabase Storage.

Imita las operaciones de storage3 que usa ObjectStorage: upload, download, exists,
remove y list. Guarda los archivos en memoria, asi que ninguna prueba unitaria toca la
red ni un bucket real.
"""

# list() se llama como el metodo de storage3 y tapa al tipo list dentro de la clase:
# las anotaciones se dejan sin evaluar para que list[str] siga siendo el tipo.
from __future__ import annotations

from typing import Any

from storage3.utils import StorageException


class InMemoryBucket:
    """Bucket en memoria con la misma forma que el cliente de storage3."""

    def __init__(self, events: list[str] | None = None) -> None:
        self.events = events if events is not None else []
        self.files: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        # operacion -> (excepcion, llamadas que todavia salen bien antes de fallar)
        self.failures: dict[str, tuple[Exception, int]] = {}

    def fail_next(self, operation: str, error: Exception, after: int = 0) -> None:
        """Hace que la operacion lance el error, despues de `after` llamadas correctas."""
        self.failures[operation] = (error, after)

    def _raise_if_failing(self, operation: str) -> None:
        pending = self.failures.get(operation)
        if pending is None:
            return
        error, remaining = pending
        if remaining > 0:
            self.failures[operation] = (error, remaining - 1)
            return
        del self.failures[operation]
        raise error

    def upload(
        self,
        path: str,
        file: bytes,
        file_options: dict[str, Any] | None = None,
    ) -> None:
        self.events.append(f"upload:{path}")
        self._raise_if_failing("upload")
        options = file_options or {}
        if path in self.files and str(options.get("upsert", "false")).lower() != "true":
            raise StorageException("El recurso ya existe")
        self.files[path] = bytes(file)
        self.content_types[path] = str(options.get("content-type", ""))

    def download(self, path: str) -> bytes:
        self.events.append(f"download:{path}")
        self._raise_if_failing("download")
        if path not in self.files:
            raise StorageException("Objeto no encontrado")
        return self.files[path]

    def exists(self, path: str) -> bool:
        self.events.append(f"exists:{path}")
        self._raise_if_failing("exists")
        return path in self.files

    def remove(self, paths: list[str]) -> list[dict[str, str]]:
        """Borra las rutas que existen e ignora las que no, como storage3."""
        self.events.append(f"remove:{','.join(paths)}")
        self._raise_if_failing("remove")
        removed = []
        for path in paths:
            if self.files.pop(path, None) is not None:
                self.content_types.pop(path, None)
                removed.append({"name": path})
        return removed

    def list(self, path: str | None = None, options: dict[str, Any] | None = None) -> list[dict]:
        """Como storage3: lo que hay directamente en la carpeta. Los archivos traen id; las
        subcarpetas, id None. Una carpeta que no existe da una lista vacia."""
        self.events.append(f"list:{path}")
        self._raise_if_failing("list")
        prefix = f"{path.rstrip('/')}/" if path else ""
        entries: dict[str, dict[str, Any]] = {}
        for stored in sorted(self.files):
            if not stored.startswith(prefix):
                continue
            rest = stored[len(prefix):]
            name, _, below = rest.partition("/")
            entries.setdefault(name, {"name": name, "id": None if below else f"id-{stored}"})
        return list(entries.values())

    def uploaded_paths(self) -> list[str]:
        """Rutas de los archivos que hay ahora en el bucket, en orden alfabetico."""
        return sorted(self.files)
