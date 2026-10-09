"""Conexion a PostgreSQL mediante el pooler de sesion de Supabase.

El grupo de conexiones se abre una sola vez al arrancar el sistema y se cierra al
apagarlo. Las peticiones lo reutilizan: ninguna abre una conexion propia.

Los tamanos del grupo y el tiempo de espera son decisiones de diseno, no
mediciones (specs/001-persistence-schema-migration/research.md, R1). El
repositorio no dice cuantos clientes admite el pooler en el plan gratuito.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from radvol3d.domain.exceptions import DatabaseUnavailableError
from radvol3d.persistence.database_errors import translate_database_error
from radvol3d.persistence.settings import Settings

POOL_MIN_SIZE = 1
POOL_MAX_SIZE = 4
POOL_TIMEOUT_SEC = 10.0


class Database:
    """Grupo de conexiones y unidad de trabajo.

    transaction() entrega una conexion dentro de una transaccion: se confirma al
    salir sin error y se revierte si hay una excepcion. Los repositorios reciben
    esa conexion, asi que varios pueden confirmar juntos o ninguno.
    """

    def __init__(
        self,
        conninfo: str,
        *,
        pool_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._conninfo = conninfo
        self._pool_factory = pool_factory or ConnectionPool
        self._pool: Any | None = None

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        pool_factory: Callable[..., Any] | None = None,
    ) -> "Database":
        """Arma la base con la URL de la configuracion. No abre ninguna conexion."""
        return cls(settings.database_url.get_secret_value(), pool_factory=pool_factory)

    def open(self) -> None:
        """Abre el grupo y espera a que este listo. Abrirlo dos veces no hace nada."""
        if self._pool is not None:
            return
        pool = None
        try:
            pool = self._pool_factory(
                self._conninfo,
                min_size=POOL_MIN_SIZE,
                max_size=POOL_MAX_SIZE,
                timeout=POOL_TIMEOUT_SEC,
                open=False,
                kwargs={"row_factory": dict_row},
            )
            pool.open(wait=True, timeout=POOL_TIMEOUT_SEC)
        except psycopg.Error as error:
            if pool is not None:
                pool.close()  # no dejar hilos del grupo corriendo tras un arranque fallido
            raise _unavailable(error) from None
        self._pool = pool

    def close(self) -> None:
        """Cierra el grupo. Si nunca se abrio, no hace nada."""
        if self._pool is None:
            return
        self._pool.close()
        self._pool = None

    @contextmanager
    def transaction(self) -> Iterator[Connection]:
        """Entrega una conexion en una transaccion: se confirma o se revierte entera."""
        if self._pool is None:
            raise DatabaseUnavailableError("La conexion con la base de datos no esta abierta.")
        try:
            with self._pool.connection() as connection, connection.transaction():
                yield connection
        except psycopg.Error as error:
            # La unidad de trabajo ya se revirtio al salir del bloque with.
            raise translate_database_error(error) from None


def _unavailable(error: psycopg.Error) -> DatabaseUnavailableError:
    """Error de arranque: cualquier fallo al abrir el grupo significa base no disponible.

    Se pasa por translate_database_error para registrar el sqlstate, pero el mensaje
    nunca copia el de psycopg, que puede traer la URL con su contrasena.
    """
    translated = translate_database_error(error)
    if isinstance(translated, DatabaseUnavailableError):
        return translated
    return DatabaseUnavailableError("No se pudo abrir la conexion con la base de datos.")
