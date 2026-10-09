"""Fixtures de las pruebas de integracion de la persistencia.

Estas pruebas leen SOLO .env.test, nunca .env, para que ninguna pueda escribir en
la base real por error. Si .env.test no existe, se omiten.

Los codigos de estudio llevan el prefijo "it_". Al terminar, la limpieza borra los
estudios con ese prefijo (las proyecciones, etapas y lesiones se borran en
cascada), los pacientes que la prueba haya creado y los archivos del bucket. Ese
codigo de limpieza vive solo aqui: la capa de persistencia no tiene borrado.
"""

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from dotenv import dotenv_values
from pydantic import SecretStr

from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.settings import Settings

ENV_TEST_FILE = Path(__file__).resolve().parents[3] / ".env.test"
STUDY_PREFIX = "it_"
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
        return f"{STUDY_PREFIX}{uuid.uuid4().hex[:12]}"

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
            "select study_code from study where study_code like %s", (f"{STUDY_PREFIX}%",)
        ).fetchall()
        study_codes = [row["study_code"] for row in rows]
        connection.execute("delete from study where study_code like %s", (f"{STUDY_PREFIX}%",))
        # Los modelos de prueba se borran despues de los estudios que los usaban.
        connection.execute("delete from model where model_name like %s", (f"{STUDY_PREFIX}%",))
        for patient_code in created_patient_codes:
            if patient_code != "PAC000000":
                connection.execute(
                    "delete from patient where patient_code = %s "
                    "and not exists (select 1 from study "
                    "where study.patient_id = patient.patient_id)",
                    (patient_code,),
                )

    # El cliente de storage3 se usa directamente: ObjectStorage no borra archivos.
    bucket = object_storage._bucket  # noqa: SLF001
    for study_code in study_codes:
        paths = [
            f"{study_code}/projections/angle_{angle:03d}.npy" for angle in (0, 45, 90, 135)
        ] + [
            f"{study_code}/volume.npy",
            f"{study_code}/segmentation/mask.npy",
            f"{study_code}/segmentation/probability.npy",
            f"{study_code}/segmentation/summary.json",
            f"{study_code}/meshes/organ.glb",
            f"{study_code}/meshes/tumor.glb",
        ]
        bucket.remove(paths)
