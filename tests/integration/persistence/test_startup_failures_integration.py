"""Fallos de arranque contra un servidor que no responde (historia 4).

A diferencia de las demas pruebas de integracion, esta NO necesita un Supabase de
prueba ni .env.test: justamente apunta a servidores que no existen. Solo necesita
poder resolver nombres de red y abrir sockets locales.
"""

import pytest

from radvol3d.domain.exceptions import DatabaseUnavailableError
from radvol3d.persistence import connection as connection_module
from radvol3d.persistence.connection import Database

pytestmark = pytest.mark.integration

PASSWORD = "db-password-1"

# Con ids explicitos: si el id fuera la URL, la contrasena iria a los registros de pytest.
UNREACHABLE_URLS = [
    # El nombre no se resuelve: el dominio .invalid esta reservado para eso (RFC 2606).
    pytest.param(
        f"postgresql://user:{PASSWORD}@servidor-que-no-existe.invalid:5432/postgres",
        id="host_que_no_se_resuelve",
    ),
    # El puerto 1 de la propia maquina rechaza la conexion.
    pytest.param(f"postgresql://user:{PASSWORD}@127.0.0.1:1/postgres", id="puerto_cerrado"),
]


@pytest.fixture(autouse=True)
def short_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reduce la espera al abrir para que la prueba no tarde los 10 s reales."""
    monkeypatch.setattr(connection_module, "POOL_TIMEOUT_SEC", 2.0)


@pytest.mark.parametrize("url", UNREACHABLE_URLS)
def test_opening_against_a_server_that_does_not_exist_means_unavailable(url: str) -> None:
    database = Database(url)

    with pytest.raises(DatabaseUnavailableError) as raised:
        database.open()

    message = str(raised.value)
    assert "base de datos" in message
    assert PASSWORD not in message
    assert PASSWORD not in repr(raised.value)
    assert raised.value.__cause__ is None


@pytest.mark.parametrize("url", UNREACHABLE_URLS)
def test_a_failed_open_leaves_the_database_closed_and_reusable(url: str) -> None:
    database = Database(url)

    with pytest.raises(DatabaseUnavailableError):
        database.open()

    with pytest.raises(DatabaseUnavailableError), database.transaction():
        pass
    database.close()
