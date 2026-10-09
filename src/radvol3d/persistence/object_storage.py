"""Lectura y escritura de objetos en Supabase Storage.

Recibe el cliente del bucket ya armado, para poder probarlo con un bucket en
memoria. Los arreglos se guardan como .npy y SIEMPRE con allow_pickle=False: un
archivo con objetos serializados de Python podria ejecutar codigo al leerse.

Los errores de storage3 y de la red se traducen a errores del dominio con mensaje
propio, sin copiar el texto original y sin encadenar la causa.

Las llamadas al bucket de una misma instancia se hacen de a una (un candado por
instancia). El cliente HTTP de Supabase no admite dos peticiones a la vez desde
hilos distintos: con dos estudios en paralelo, una subida fallaba con
httpx.ReadError. Serializar solo afecta a la transferencia; la inferencia, que es
lo lento, sigue en paralelo (funcionalidad 002, FR-020).
"""

import io
import logging
import threading
from collections.abc import Sequence
from typing import Any

import httpx
import numpy as np
from storage3.utils import StorageException
from supabase import create_client

from radvol3d.domain.exceptions import StorageError, StorageObjectNotFoundError
from radvol3d.persistence.settings import Settings

CONTENT_TYPE_ARRAY = "application/octet-stream"
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_MESH = "model/gltf-binary"

_STORAGE_ERRORS = (StorageException, httpx.HTTPError)

# Librerias que, con el registro en DEBUG, escriben las cabeceras de cada peticion. hpack
# (compresion de cabeceras de HTTP/2) registra "apikey" con la clave de servicio.
_LOGGERS_THAT_WRITE_HEADERS = ("hpack",)


def _keep_credentials_out_of_debug_logs() -> None:
    """Sube esos loggers a WARNING para que la clave de servicio no llegue a los registros.

    No baja el nivel de un logger que ya sea mas estricto.
    """
    for name in _LOGGERS_THAT_WRITE_HEADERS:
        logger = logging.getLogger(name)
        if logger.level < logging.WARNING:
            logger.setLevel(logging.WARNING)


class ObjectStorage:
    """Subir, bajar, comprobar y borrar archivos en el bucket del proyecto."""

    def __init__(self, bucket: Any) -> None:
        self._bucket = bucket
        self._lock = threading.Lock()

    @classmethod
    def from_settings(cls, settings: Settings, bucket: str | None = None) -> "ObjectStorage":
        """Arma el cliente del bucket con la URL, la clave de servicio y el nombre del bucket.

        Sin bucket, abre el bucket de datos (settings.storage_bucket). Con bucket, abre
        ese otro con las mismas credenciales: asi se abre el bucket de modelos.
        """
        _keep_credentials_out_of_debug_logs()
        client = create_client(
            settings.supabase_url,
            settings.supabase_service_key.get_secret_value(),
        )
        return cls(client.storage.from_(bucket or settings.storage_bucket))

    def upload_bytes(self, path: str, data: bytes, content_type: str) -> None:
        """Sube un archivo. Si la ruta ya esta ocupada, reemplaza el anterior."""
        try:
            with self._lock:
                self._bucket.upload(
                    path,
                    data,
                    {"content-type": content_type, "upsert": "true"},
                )
        except _STORAGE_ERRORS:
            raise StorageError(f"No se pudo subir el archivo '{path}' al almacenamiento.") from None

    def download_bytes(self, path: str) -> bytes:
        """Baja un archivo. Distingue "no existe" de un fallo de acceso."""
        try:
            with self._lock:
                return self._bucket.download(path)
        except _STORAGE_ERRORS:
            pass
        if self._is_missing(path):
            raise StorageObjectNotFoundError(f"El archivo '{path}' no existe en el almacenamiento.")
        raise StorageError(f"No se pudo leer el archivo '{path}' del almacenamiento.")

    def exists(self, path: str) -> bool:
        """Indica si el archivo esta en el bucket."""
        try:
            with self._lock:
                return bool(self._bucket.exists(path))
        except _STORAGE_ERRORS:
            raise StorageError(
                f"No se pudo comprobar si existe el archivo '{path}' en el almacenamiento."
            ) from None

    def remove_many(self, paths: Sequence[str]) -> None:
        """Borra los archivos en una sola llamada. Una ruta que no existe no es error."""
        if not paths:
            return
        try:
            with self._lock:
                self._bucket.remove(list(paths))
        except _STORAGE_ERRORS:
            raise StorageError("No se pudieron borrar los archivos del almacenamiento.") from None

    def upload_array(self, path: str, array: np.ndarray) -> None:
        """Guarda un arreglo como .npy, sin objetos serializados."""
        buffer = io.BytesIO()
        try:
            np.save(buffer, array, allow_pickle=False)
        except (ValueError, TypeError):
            raise StorageError(
                "El arreglo contiene objetos de Python y no se puede guardar como .npy."
            ) from None
        self.upload_bytes(path, buffer.getvalue(), CONTENT_TYPE_ARRAY)

    def download_array(self, path: str) -> np.ndarray:
        """Lee un arreglo .npy. Rechaza los archivos con objetos serializados."""
        data = self.download_bytes(path)
        try:
            loaded = np.load(io.BytesIO(data), allow_pickle=False)
        except (ValueError, OSError, EOFError):
            loaded = None
        if not isinstance(loaded, np.ndarray):
            raise StorageError(
                f"El archivo '{path}' no es un arreglo .npy valido o contiene objetos serializados."
            )
        return loaded

    def _is_missing(self, path: str) -> bool:
        """True solo si el bucket responde que el archivo no existe."""
        try:
            with self._lock:
                return not self._bucket.exists(path)
        except _STORAGE_ERRORS:
            return False
