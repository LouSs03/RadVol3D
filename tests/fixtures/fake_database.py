"""Dobles de la base de datos.

Permiten probar los repositorios y los almacenes sin PostgreSQL y sin red. No
verifican el SQL contra una base real: eso lo hacen las pruebas de integracion.
Lo que si verifican es que los repositorios envien los parametros correctos, que
conviertan bien las filas en entidades y que traduzcan los errores de psycopg.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import psycopg.errors as pg_errors


def normalize_sql(sql: str) -> str:
    """Pasa el SQL a minusculas y colapsa los espacios, para compararlo con facilidad."""
    return re.sub(r"\s+", " ", sql).strip().lower()


class FakeCursor:
    """Resultado de un execute: guarda las filas y la cantidad de filas afectadas."""

    def __init__(self, rows: list[dict[str, Any]], rowcount: int | None = None) -> None:
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount

    def fetchone(self) -> dict[str, Any] | None:
        return self._rows.pop(0) if self._rows else None

    def fetchall(self) -> list[dict[str, Any]]:
        rows, self._rows = self._rows, []
        return rows


class FakeConnection:
    """Conexion guionada.

    Hay dos formas de guionarla, y se pueden combinar:

    - Una cola: cada llamada a execute consume la siguiente respuesta.
    - Reglas por fragmento de SQL (when): la primera regla cuyo fragmento aparece en
      el SQL normalizado decide la respuesta. Registra primero las mas especificas.

    Una respuesta puede ser una lista de filas (diccionarios), un FakeCursor ya
    armado o una excepcion, que se lanza. Si nada responde, devuelve un resultado sin
    filas con rowcount igual a default_rowcount (1, como un insert que afecta una fila).
    """

    def __init__(
        self,
        responses: list[Any] | None = None,
        events: list[str] | None = None,
        default_rowcount: int = 1,
    ) -> None:
        self.responses: list[Any] = list(responses or [])
        self.rules: list[tuple[str, Any, bool]] = []
        self.events = events if events is not None else []
        self.calls: list[tuple[str, Any]] = []
        self.default_rowcount = default_rowcount

    def queue(self, *responses: Any) -> None:
        """Agrega respuestas al final de la cola."""
        self.responses.extend(responses)

    def when(self, fragment: str, response: Any, once: bool = False) -> None:
        """Responde con la respuesta dada a todo SQL que contenga el fragmento."""
        self.rules.append((fragment.lower(), response, once))

    def execute(self, sql: str, params: Any = None) -> FakeCursor:
        self.calls.append((sql, params))
        self.events.append(f"sql:{normalize_sql(sql)}")
        return self._next_cursor(normalize_sql(sql))

    def executemany(self, sql: str, params_seq: Any) -> None:
        batch = list(params_seq)
        self.calls.append((sql, batch))
        self.events.append(f"sql:{normalize_sql(sql)}")
        self._next_cursor(normalize_sql(sql))

    def _next_cursor(self, normalized_sql: str) -> FakeCursor:
        if self.responses:
            return self._as_cursor(self.responses.pop(0))
        for position, (fragment, response, once) in enumerate(self.rules):
            if fragment in normalized_sql:
                if once:
                    del self.rules[position]
                return self._as_cursor(response)
        return FakeCursor([], rowcount=self.default_rowcount)

    @staticmethod
    def _as_cursor(response: Any) -> FakeCursor:
        if isinstance(response, BaseException):
            raise response
        if isinstance(response, FakeCursor):
            return response
        # Cada ejecucion recibe su propia copia de las filas.
        return FakeCursor([dict(row) for row in response])

    def statements(self) -> list[str]:
        """SQL ejecutado, normalizado, en el orden en que se ejecuto."""
        return [normalize_sql(sql) for sql, _ in self.calls]

    def params_of(self, fragment: str) -> list[Any]:
        """Parametros de cada sentencia cuyo SQL contiene el fragmento."""
        needle = fragment.lower()
        return [params for sql, params in self.calls if needle in normalize_sql(sql)]


class FakeDatabase:
    """Sustituto de Database: su transaction() entrega siempre la misma conexion."""

    def __init__(
        self,
        connection: FakeConnection | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.events = events if events is not None else []
        self.connection = connection or FakeConnection(events=self.events)
        self.connection.events = self.events
        self.committed = 0
        self.rolled_back = 0

    @contextmanager
    def transaction(self) -> Iterator[FakeConnection]:
        try:
            yield self.connection
        except BaseException:
            self.rolled_back += 1
            self.events.append("db:rollback")
            raise
        else:
            self.committed += 1
            self.events.append("db:commit")


class _ConstraintInfo:
    """Aporta diag.constraint_name sin necesitar una conexion real a PostgreSQL."""

    def __init__(self, constraint_name: str | None) -> None:
        self._constraint_name = constraint_name

    @property
    def diag(self) -> SimpleNamespace:
        return SimpleNamespace(constraint_name=self._constraint_name)


class FakeUniqueViolation(_ConstraintInfo, pg_errors.UniqueViolation):
    def __init__(self, constraint_name: str | None = None, message: str = "") -> None:
        pg_errors.UniqueViolation.__init__(self, message)
        _ConstraintInfo.__init__(self, constraint_name)


class FakeCheckViolation(_ConstraintInfo, pg_errors.CheckViolation):
    def __init__(self, constraint_name: str | None = None, message: str = "") -> None:
        pg_errors.CheckViolation.__init__(self, message)
        _ConstraintInfo.__init__(self, constraint_name)


class FakeForeignKeyViolation(_ConstraintInfo, pg_errors.ForeignKeyViolation):
    def __init__(self, constraint_name: str | None = None, message: str = "") -> None:
        pg_errors.ForeignKeyViolation.__init__(self, message)
        _ConstraintInfo.__init__(self, constraint_name)


class FakeIntegrityError(_ConstraintInfo, pg_errors.IntegrityError):
    def __init__(self, constraint_name: str | None = None, message: str = "") -> None:
        pg_errors.IntegrityError.__init__(self, message)
        _ConstraintInfo.__init__(self, constraint_name)


class FakeOperationalError(_ConstraintInfo, pg_errors.OperationalError):
    def __init__(self, message: str = "") -> None:
        pg_errors.OperationalError.__init__(self, message)
        _ConstraintInfo.__init__(self, None)


def index_of(events: list[str], fragment: str) -> int:
    """Posicion del primer evento que contiene el fragmento, o -1 si no hay ninguno."""
    needle = fragment.lower()
    for position, event in enumerate(events):
        if needle in event.lower():
            return position
    return -1
