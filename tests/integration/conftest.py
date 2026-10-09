"""Fixtures compartidas por las pruebas de integracion (persistencia y servicios).

Estas pruebas leen SOLO .env.test, nunca .env, para que ninguna pueda escribir en
la base real por error. Si .env.test no existe, se omiten.

Los codigos de estudio llevan el prefijo de la sesion, SESSION_PREFIX ("it_<token>_").
Al terminar cada prueba, la limpieza borra los estudios con ESE prefijo, no todos los
"it_": si dos sesiones comparten la base de prueba (dos terminales, otro agente), la
limpieza de una no borra los estudios que la otra esta usando. Los borra con
StudyMetadataStore.delete_study (filas en cascada, sus diez archivos fijos del bucket
y las mallas de lesion de <codigo>/meshes). Solo quedan en SQL directo, aqui y en
ningun otro lugar, dos cosas que la persistencia no borra a proposito: los pacientes y los
modelos que la prueba haya creado, y un estudio que haya quedado en processing.
"""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import SecretStr

from radvol3d.domain.exceptions import StudyInProgressError
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.settings import Settings
from radvol3d.persistence.study_metadata_store import StudyMetadataStore

ENV_TEST_FILE = Path(__file__).resolve().parents[2] / ".env.test"
STUDY_PREFIX = "it_"
# Unico por sesion de pytest: la limpieza solo toca lo que creo esta sesion.
SESSION_PREFIX = f"{STUDY_PREFIX}{uuid.uuid4().hex[:6]}_"
REQUIRED_VARIABLES = ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_SERVICE_KEY", "STORAGE_BUCKET")


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Configuracion del Supabase de prueba, leida solo de .env.test."""
    if not ENV_TEST_FILE.is_file():
        pytest.skip("Falta .env.test: copia .env.test.example y apunta a un Supabase de prueba")
    values = dotenv_values(ENV_TEST_FILE)
    missing = [name for name in REQUIRED_VARIABLES if not values.get(name)]
    if missing:
        pytest.skip(f".env.test esta incompleto, faltan: {', '.join(missing)}")
    return Settings(
        _env_file=None,
        database_url=SecretStr(values["DATABASE_URL"]),
        supabase_url=values["SUPABASE_URL"],
        supabase_service_key=SecretStr(values["SUPABASE_SERVICE_KEY"]),
        storage_bucket=values["STORAGE_BUCKET"],
    )


@pytest.fixture(scope="session")
def database(test_settings: Settings) -> Iterator[Database]:
    """Base de datos de prueba, abierta una sola vez por sesion."""
    db = Database.from_settings(test_settings)
    db.open()
    yield db
    db.close()


@pytest.fixture(scope="session")
def object_storage(test_settings: Settings) -> ObjectStorage:
    """Almacenamiento de objetos sobre el bucket de prueba."""
    return ObjectStorage.from_settings(test_settings)


@pytest.fixture
def make_study_code() -> Callable[[], str]:
    """Fabrica de codigos de estudio unicos con el prefijo de pruebas."""

    def _make() -> str:
        return f"{SESSION_PREFIX}{uuid.uuid4().hex[:12]}"

    return _make


@pytest.fixture
def created_patient_codes() -> list[str]:
    """Lista donde cada prueba anota los codigos de paciente que creo, para limpiarlos."""
    return []


@pytest.fixture(autouse=True)
def cleanup_after_test(
    request: pytest.FixtureRequest,
    created_patient_codes: list[str],
) -> Iterator[None]:
    """Borra los estudios, pacientes y archivos que la prueba haya dejado.

    Las fixtures de la base y del bucket se piden ANTES del yield: pedirlas durante
    el teardown esta deprecado en pytest. Las pruebas que no usan la base (las de
    fallos de arranque) no la piden y por eso no necesitan .env.test.
    """
    uses_database = "database" in request.fixturenames
    database: Database | None = request.getfixturevalue("database") if uses_database else None
    object_storage: ObjectStorage | None = (
        request.getfixturevalue("object_storage") if uses_database else None
    )
    yield
    if database is None or object_storage is None:
        return

    with database.transaction() as connection:
        rows = connection.execute(
            "select study_code from study where study_code like %s", (f"{SESSION_PREFIX}%",)
        ).fetchall()
    metadata = StudyMetadataStore(database, object_storage)
    for row in rows:
        try:
            metadata.delete_study(row["study_code"])
        except StudyInProgressError:
            # Una prueba que fallo a mitad de la tuberia deja el estudio en processing.
            with database.transaction() as connection:
                connection.execute(
                    "update study set status = 'failed' where study_code = %s",
                    (row["study_code"],),
                )
            metadata.delete_study(row["study_code"])

    with database.transaction() as connection:
        # Los modelos de prueba se borran despues de los estudios que los usaban.
        connection.execute("delete from model where model_name like %s", (f"{SESSION_PREFIX}%",))
        for patient_code in created_patient_codes:
            if patient_code != "PAC000000":
                connection.execute(
                    "delete from patient where patient_code = %s "
                    "and not exists (select 1 from study "
                    "where study.patient_id = patient.patient_id)",
                    (patient_code,),
                )
