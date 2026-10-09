"""Pruebas de la configuracion de la capa de persistencia.

Todas construyen Settings con _env_file=None (o con un archivo temporal) para no
leer nunca el .env real del repositorio.
"""

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr

from radvol3d.domain.exceptions import ConfigurationError
from radvol3d.persistence import settings as settings_module
from radvol3d.persistence.settings import Settings, get_settings

VARIABLES = {
    "DATABASE_URL": "postgresql://user:db-password-1@host.example:5432/postgres",
    "SUPABASE_URL": "https://project.example",
    "SUPABASE_SERVICE_KEY": "service-key-value-1",
    "STORAGE_BUCKET": "bucket-de-prueba",
}
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def full_environment(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    for name, value in VARIABLES.items():
        monkeypatch.setenv(name, value)
    return dict(VARIABLES)


@pytest.fixture(autouse=True)
def fresh_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.unit
def test_settings_expose_the_four_variables(full_environment: dict[str, str]) -> None:
    settings = Settings(_env_file=None)

    assert settings.database_url.get_secret_value() == VARIABLES["DATABASE_URL"]
    assert settings.supabase_url == VARIABLES["SUPABASE_URL"]
    assert settings.supabase_service_key.get_secret_value() == VARIABLES["SUPABASE_SERVICE_KEY"]
    assert settings.storage_bucket == VARIABLES["STORAGE_BUCKET"]


@pytest.mark.unit
def test_credentials_are_secret_strings(full_environment: dict[str, str]) -> None:
    settings = Settings(_env_file=None)

    assert isinstance(settings.database_url, SecretStr)
    assert isinstance(settings.supabase_service_key, SecretStr)


@pytest.mark.unit
def test_get_settings_loads_once_and_keeps_the_result(full_environment: dict[str, str]) -> None:
    first = get_settings()
    second = get_settings()

    assert first is second


@pytest.mark.unit
def test_the_env_file_is_read_from_the_repository_root() -> None:
    assert Path(settings_module.ENV_FILE) == REPOSITORY_ROOT / ".env"


@pytest.mark.unit
def test_values_are_read_from_an_env_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(f"{name}={value}" for name, value in VARIABLES.items()), encoding="utf-8"
    )

    settings = Settings(_env_file=env_file)

    assert settings.storage_bucket == VARIABLES["STORAGE_BUCKET"]


@pytest.mark.unit
def test_the_environment_takes_priority_over_the_env_file(
    tmp_path: Path, full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("STORAGE_BUCKET=bucket-del-archivo", encoding="utf-8")
    monkeypatch.setenv("STORAGE_BUCKET", "bucket-del-entorno")

    settings = Settings(_env_file=env_file)

    assert settings.storage_bucket == "bucket-del-entorno"


@pytest.mark.unit
def test_importing_the_module_does_not_fail_without_variables() -> None:
    environment = {k: v for k, v in os.environ.items() if k not in VARIABLES}
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT / "src")

    result = subprocess.run(
        [sys.executable, "-c", "import radvol3d.persistence.settings"],
        env=environment,
        capture_output=True,
        text=True,
        cwd=REPOSITORY_ROOT,
        check=False,
    )

    assert result.returncode == 0, result.stderr


# --- Historia 4: arrancar con configuracion valida o no arrancar (FR-008, FR-009) ---

DB_PASSWORD = "db-password-1"
SERVICE_KEY = VARIABLES["SUPABASE_SERVICE_KEY"]
PYDANTIC_WORDS = ["input_value", "validation error", "Field required", "pydantic", "should have"]


@pytest.fixture(autouse=True)
def ignore_the_real_env_file(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_settings() no debe leer el .env real del repositorio durante estas pruebas."""
    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.mark.unit
@pytest.mark.parametrize("name", list(VARIABLES))
def test_a_missing_variable_stops_startup_and_names_it(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.delenv(name)

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    assert name in str(raised.value)
    assert str(raised.value).startswith("Falta")


@pytest.mark.unit
@pytest.mark.parametrize("name", list(VARIABLES))
def test_an_empty_variable_counts_as_missing(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setenv(name, "")

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    assert name in str(raised.value)


@pytest.mark.unit
def test_several_missing_variables_are_all_named(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DATABASE_URL")
    monkeypatch.delenv("STORAGE_BUCKET")

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    message = str(raised.value)
    assert "DATABASE_URL" in message
    assert "STORAGE_BUCKET" in message
    assert "SUPABASE_URL" not in message
    assert message.startswith("Faltan")


@pytest.mark.unit
def test_with_nothing_configured_all_four_variables_are_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    assert all(name in str(raised.value) for name in VARIABLES)


@pytest.mark.unit
@pytest.mark.parametrize("name", list(VARIABLES))
def test_the_message_never_copies_the_pydantic_text(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.delenv(name)

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    for word in PYDANTIC_WORDS:
        assert word not in str(raised.value)


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["DATABASE_URL", "SUPABASE_SERVICE_KEY", "STORAGE_BUCKET"])
def test_the_error_never_shows_a_credential_that_is_set(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    monkeypatch.delenv(missing)

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    assert SERVICE_KEY not in str(raised.value)
    assert DB_PASSWORD not in str(raised.value)
    assert SERVICE_KEY not in repr(raised.value)
    assert DB_PASSWORD not in repr(raised.value)


@pytest.mark.unit
def test_the_error_has_no_cause_to_leak_through_a_traceback(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("SUPABASE_URL")

    with pytest.raises(ConfigurationError) as raised:
        get_settings()

    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


@pytest.mark.unit
def test_the_text_of_the_settings_never_shows_the_credentials(
    full_environment: dict[str, str],
) -> None:
    settings = Settings(_env_file=None)

    shown = f"{settings!s} {settings!r} {settings.model_dump()} {settings.model_dump_json()}"

    assert SERVICE_KEY not in shown
    assert DB_PASSWORD not in shown


@pytest.mark.unit
def test_a_failed_startup_is_not_cached_and_a_later_one_can_succeed(
    full_environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("STORAGE_BUCKET")
    with pytest.raises(ConfigurationError):
        get_settings()

    monkeypatch.setenv("STORAGE_BUCKET", "bucket-de-prueba")

    assert get_settings().storage_bucket == "bucket-de-prueba"
