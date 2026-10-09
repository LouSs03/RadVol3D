"""La aplicacion completa con las estrategias dobles y el Supabase de prueba.

Es la misma aplicacion que levanta main.py, con su lifespan, sus routers y su
contenedor de servicios real (base, bucket, almacenes y tuberia). Solo cambian las
estrategias: reconstruccion, segmentacion y mallas son los dobles de
tests/fixtures/fake_strategies.py, asi que no hace falta torch ni pesos y un estudio
se procesa en segundos.

La configuracion sale SOLO de .env.test, nunca de .env: nada de lo que se haga aqui
puede tocar la base real.

Uso:
    - en las pruebas e2e: TestClient(create_app_with_fakes())
    - para el recorrido manual de quickstart.md:
      uvicorn --factory tests.e2e.app_with_fakes:create_app_with_fakes
"""

from pathlib import Path

from dotenv import dotenv_values
from fastapi import FastAPI
from pydantic import SecretStr

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ConfigurationError
from radvol3d.main import create_app
from radvol3d.persistence.settings import ModelSettings, Settings
from radvol3d.services.service_container import (
    ServiceContainer,
    StrategyBuilders,
    build_service_container,
)
from tests.fixtures.fake_strategies import (
    FakeMeshingStrategy,
    FakeReconstructionStrategy,
    FakeSegmentationStrategy,
)

ENV_TEST_FILE = Path(__file__).resolve().parents[2] / ".env.test"
REQUIRED_VARIABLES = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "STORAGE_BUCKET")


def settings_from_env_test() -> Settings:
    """La configuracion del Supabase de prueba. Lanza ConfigurationError si falta."""
    if not ENV_TEST_FILE.is_file():
        raise ConfigurationError(
            "Falta .env.test: copia .env.test.example y apunta a un Supabase de prueba."
        )
    values = dotenv_values(ENV_TEST_FILE)
    missing = [name for name in REQUIRED_VARIABLES if not values.get(name)]
    if missing:
        raise ConfigurationError(f".env.test esta incompleto, faltan: {', '.join(missing)}.")
    return Settings(
        _env_file=None,
        database_url=SecretStr(values["DATABASE_URL"]),
        supabase_url=values["SUPABASE_URL"],
        supabase_service_key=SecretStr(values["SUPABASE_SERVICE_KEY"]),
        storage_bucket=values["STORAGE_BUCKET"],
    )


def build_container_with_fakes() -> ServiceContainer:
    """El contenedor real, con las estrategias dobles y sin bucket de modelos."""
    return build_service_container(
        settings_from_env_test(),
        ModelSettings(_env_file=None),
        strategy_builders=StrategyBuilders(
            reconstruction={"en1": FakeReconstructionStrategy},
            segmentation={OrganName.LUNG: FakeSegmentationStrategy},
            meshing=FakeMeshingStrategy,
        ),
    )


def create_app_with_fakes() -> FastAPI:
    """La aplicacion completa; el contenedor se arma recien al arrancar (lifespan)."""
    settings_from_env_test()  # falla temprano y claro si falta .env.test
    return create_app(container_builder=build_container_with_fakes)
