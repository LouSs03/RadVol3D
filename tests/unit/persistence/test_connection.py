"""Pruebas de la conexion a la base de datos, con un grupo de conexiones falso."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg_pool import PoolTimeout
from pydantic import SecretStr

from radvol3d.domain.exceptions import (
    DatabaseUnavailableError,
    DuplicateStudyError,
    StudyNotFoundError,
)
from radvol3d.persistence.connection import Database
from radvol3d.persistence.settings import Settings
from tests.fixtures.fake_database import FakeOperationalError, FakeUniqueViolation

CONNINFO = "postgresql://user:db-password-1@host.example:5432/postgres"


class FakeTransactionConnection:
    """Conexion falsa que anota como terminaron sus transacciones."""

    def __init__(self) -> None:
        self.transactions: list[str] = []

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
        except BaseException:
            self.transactions.append("rollback")
            raise
        else:
            self.transactions.append("commit")


class FakePool:
    """Grupo falso: anota como se construyo y si se abrio o se cerro."""

    instances: list["FakePool"] = []
    # Errores que el grupo falso lanza al abrir o al entregar una conexion.
    open_error: BaseException | None = None
    connection_error: BaseException | None = None

    def __init__(self, conninfo: str, **options: Any) -> None:
        self.conninfo = conninfo
        self.options = options
        self.open_calls: list[dict[str, Any]] = []
        self.closed = 0
        self.connection_object = FakeTransactionConnection()
        FakePool.instances.append(self)

    def open(self, wait: bool = False, timeout: float = 30.0) -> None:
        self.open_calls.append({"wait": wait, "timeout": timeout})
        if FakePool.open_error is not None:
            raise FakePool.open_error

    def close(self) -> None:
        self.closed += 1

    @contextmanager
    def connection(self) -> Iterator[FakeTransactionConnection]:
        if FakePool.connection_error is not None:
            raise FakePool.connection_error
        yield self.connection_object


@pytest.fixture(autouse=True)
def reset_pools() -> None:
    FakePool.instances.clear()
    FakePool.open_error = None
    FakePool.connection_error = None


@pytest.fixture
def database() -> Database:
    return Database(CONNINFO, pool_factory=FakePool)


@pytest.mark.unit
def test_from_settings_builds_the_pool_with_the_agreed_options() -> None:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(CONNINFO),
        supabase_url="https://project.example",
        supabase_service_key=SecretStr("service-key-value-1"),
        storage_bucket="bucket-de-prueba",
    )

    Database.from_settings(settings, pool_factory=FakePool).open()

    pool = FakePool.instances[0]
    assert pool.conninfo == CONNINFO
    assert pool.options["min_size"] == 1
    assert pool.options["max_size"] == 4
    assert pool.options["timeout"] == 10.0
    assert pool.options["open"] is False
    assert pool.options["kwargs"] == {"row_factory": dict_row}


@pytest.mark.unit
def test_open_waits_until_the_pool_is_ready(database: Database) -> None:
    database.open()

    assert FakePool.instances[0].open_calls == [{"wait": True, "timeout": 10.0}]


@pytest.mark.unit
def test_open_twice_builds_only_one_pool(database: Database) -> None:
    database.open()
    database.open()

    assert len(FakePool.instances) == 1
    assert len(FakePool.instances[0].open_calls) == 1


@pytest.mark.unit
def test_close_closes_the_pool(database: Database) -> None:
    database.open()

    database.close()

    assert FakePool.instances[0].closed == 1


@pytest.mark.unit
def test_close_before_open_does_nothing(database: Database) -> None:
    database.close()

    assert FakePool.instances == []


@pytest.mark.unit
def test_transaction_hands_over_the_connection_and_commits(database: Database) -> None:
    database.open()

    with database.transaction() as connection:
        assert connection is FakePool.instances[0].connection_object

    assert FakePool.instances[0].connection_object.transactions == ["commit"]


@pytest.mark.unit
def test_transaction_rolls_back_when_the_block_fails(database: Database) -> None:
    database.open()

    with pytest.raises(ValueError, match="fallo"), database.transaction():
        raise ValueError("fallo")

    assert FakePool.instances[0].connection_object.transactions == ["rollback"]


@pytest.mark.unit
def test_transaction_before_open_reports_the_database_as_unavailable(database: Database) -> None:
    with pytest.raises(DatabaseUnavailableError), database.transaction():
        pass


# --- Historia 4: la base no responde (FR-012) ---

PASSWORD = "db-password-1"


@pytest.mark.unit
def test_a_pool_that_does_not_open_in_time_means_the_database_is_unavailable(
    database: Database,
) -> None:
    FakePool.open_error = PoolTimeout("couldn't get a connection after 10.00 sec")

    with pytest.raises(DatabaseUnavailableError) as raised:
        database.open()

    assert "base de datos" in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.unit
def test_an_operational_error_on_open_means_the_database_is_unavailable(
    database: Database,
) -> None:
    FakePool.open_error = FakeOperationalError(f"connection refused to {CONNINFO}")

    with pytest.raises(DatabaseUnavailableError):
        database.open()


@pytest.mark.unit
def test_the_failed_pool_is_closed_and_the_database_can_be_opened_again(
    database: Database,
) -> None:
    FakePool.open_error = PoolTimeout("sin respuesta")
    with pytest.raises(DatabaseUnavailableError):
        database.open()
    assert FakePool.instances[0].closed == 1

    FakePool.open_error = None
    database.open()

    assert len(FakePool.instances) == 2
    with database.transaction():
        pass


@pytest.mark.unit
def test_after_a_failed_open_a_transaction_reports_the_database_as_unavailable(
    database: Database,
) -> None:
    FakePool.open_error = PoolTimeout("sin respuesta")
    with pytest.raises(DatabaseUnavailableError):
        database.open()

    with pytest.raises(DatabaseUnavailableError), database.transaction():
        pass


@pytest.mark.unit
@pytest.mark.parametrize(
    "error",
    [PoolTimeout("couldn't get a connection"), FakeOperationalError(f"server closed {CONNINFO}")],
)
def test_a_failure_getting_a_connection_means_the_database_is_unavailable(
    database: Database, error: BaseException
) -> None:
    database.open()
    FakePool.connection_error = error

    with pytest.raises(DatabaseUnavailableError), database.transaction():
        pass


@pytest.mark.unit
@pytest.mark.parametrize(
    "error", [PoolTimeout("sin respuesta"), FakeOperationalError("connection lost")]
)
def test_an_operational_error_inside_the_block_rolls_back_and_is_translated(
    database: Database, error: BaseException
) -> None:
    database.open()

    with pytest.raises(DatabaseUnavailableError), database.transaction():
        raise error

    assert FakePool.instances[0].connection_object.transactions == ["rollback"]


@pytest.mark.unit
def test_a_raw_integrity_error_escaping_the_block_is_translated_too(database: Database) -> None:
    database.open()

    with pytest.raises(DuplicateStudyError), database.transaction():
        raise FakeUniqueViolation("study_study_code_key")


@pytest.mark.unit
def test_domain_errors_pass_through_the_transaction_untouched(database: Database) -> None:
    database.open()
    original = StudyNotFoundError("No existe el estudio 'it_a'.")

    with pytest.raises(StudyNotFoundError) as raised, database.transaction():
        raise original

    assert raised.value is original
    assert FakePool.instances[0].connection_object.transactions == ["rollback"]


@pytest.mark.unit
def test_other_exceptions_pass_through_the_transaction_untouched(database: Database) -> None:
    database.open()

    with pytest.raises(ValueError, match="no es de la base"), database.transaction():
        raise ValueError("no es de la base")


@pytest.mark.unit
@pytest.mark.parametrize("when", ["open", "connection"])
def test_the_url_password_never_appears_in_the_error(database: Database, when: str) -> None:
    leaky = FakeOperationalError(f"could not connect using {CONNINFO}")
    if when == "open":
        FakePool.open_error = leaky
        with pytest.raises(DatabaseUnavailableError) as raised:
            database.open()
    else:
        database.open()
        FakePool.connection_error = leaky
        with pytest.raises(DatabaseUnavailableError) as raised, database.transaction():
            pass

    assert PASSWORD not in str(raised.value)
    assert PASSWORD not in repr(raised.value)
    assert "host.example" not in str(raised.value)


@pytest.mark.unit
def test_any_error_while_opening_means_unavailable_even_a_malformed_url(
    database: Database,
) -> None:
    FakePool.open_error = psycopg.ProgrammingError(f"invalid connection option in {CONNINFO}")

    with pytest.raises(DatabaseUnavailableError) as raised:
        database.open()

    assert PASSWORD not in str(raised.value)
    assert raised.value.__cause__ is None
