"""Historial de estudios contra el Supabase de prueba (funcionalidad 005).

La consulta agregada (left join lesion, group by, filtro por DNI) solo se puede probar
contra PostgreSQL. La base de prueba es compartida: cada prueba compara solo sus
propios codigos (prefijo de la sesion) y, al filtrar, DNI generados al azar. Se omite si
no existe .env.test.
"""

import random
from collections.abc import Callable, Iterable

import pytest

from radvol3d.domain.entities import Lesion, PatientDetails, StudyHistoryEntry
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
from radvol3d.persistence.repositories.lesion_repository import LesionRepository
from radvol3d.persistence.repositories.study_repository import StudyRepository
from radvol3d.persistence.study_metadata_store import StudyMetadataStore

pytestmark = pytest.mark.integration

PAGE = 100


@pytest.fixture
def metadata(database: Database, object_storage: ObjectStorage) -> StudyMetadataStore:
    return StudyMetadataStore(database, object_storage)


def own_entries(
    metadata: StudyMetadataStore, codes: Iterable[str], national_id: str | None = None
) -> list[StudyHistoryEntry]:
    """Recorre las paginas del historial y devuelve, en orden, las entradas de esos codigos."""
    wanted = set(codes)
    found: list[StudyHistoryEntry] = []
    offset = 0
    while True:
        page = metadata.list_history(PAGE, offset, national_id)
        found.extend(entry for entry in page.entries if entry.study_code in wanted)
        if not page.has_more or len(found) == len(wanted):
            return found
        offset += PAGE


def test_history_lists_the_studies_from_newest_to_oldest(
    metadata: StudyMetadataStore, make_study_code: Callable[[], str]
) -> None:
    codes = [make_study_code() for _ in range(3)]
    for code in codes:
        metadata.create_study(code, OrganName.LUNG)

    entries = own_entries(metadata, codes)

    assert [entry.study_code for entry in entries] == list(reversed(codes))
    assert all(entry.status is StudyStatus.PENDING for entry in entries)
    assert all(entry.organ is OrganName.LUNG for entry in entries)

    metadata.delete_study(codes[1])

    remaining = own_entries(metadata, codes)
    assert [entry.study_code for entry in remaining] == [codes[2], codes[0]]


def complete_with_lesions(database: Database, code: str, lesions: list[Lesion]) -> None:
    """Guarda las lesiones del estudio y lo deja en completed, sin correr la tuberia."""
    with database.transaction() as connection:
        LesionRepository(connection).add_many(code, lesions)
        StudyRepository(connection).update_status(code, StudyStatus.COMPLETED)


def test_history_sums_the_volume_of_every_lesion(
    metadata: StudyMetadataStore, database: Database, make_study_code: Callable[[], str]
) -> None:
    with_lesions, without_lesions = make_study_code(), make_study_code()
    metadata.create_study(with_lesions, OrganName.LUNG)
    metadata.create_study(without_lesions, OrganName.LUNG)
    complete_with_lesions(
        database,
        with_lesions,
        [Lesion("superior", 12.5, 0.9), Lesion("inferior", 30.25, 0.8)],
    )
    complete_with_lesions(database, without_lesions, [])

    entries = {e.study_code: e for e in own_entries(metadata, [with_lesions, without_lesions])}

    assert entries[with_lesions].lesion_count == 2
    assert entries[with_lesions].total_lesion_volume_mm3 == 42.75
    assert entries[without_lesions].lesion_count == 0
    assert entries[without_lesions].total_lesion_volume_mm3 == 0.0


def unused_national_id(database: Database, taken: set[str]) -> str:
    """Un DNI de ocho digitos al azar que ningun paciente de la base tiene."""
    while True:
        candidate = f"{random.randrange(10**8):08d}"
        if candidate in taken:
            continue
        with database.transaction() as connection:
            row = connection.execute(
                "select 1 from patient where national_id = %s", (candidate,)
            ).fetchone()
        if row is None:
            taken.add(candidate)
            return candidate


def test_history_filters_by_national_id(
    metadata: StudyMetadataStore,
    database: Database,
    make_study_code: Callable[[], str],
    created_patient_codes: list[str],
) -> None:
    taken: set[str] = set()
    dni_x, dni_y, dni_none = (unused_national_id(database, taken) for _ in range(3))
    first_x, other_y, second_x, anonymous = (make_study_code() for _ in range(4))
    for code, national_id in ((first_x, dni_x), (other_y, dni_y), (second_x, dni_x)):
        study = metadata.create_study(
            code,
            OrganName.LUNG,
            PatientDetails(first_name="Prueba", last_name="Historial", national_id=national_id),
        )
        created_patient_codes.append(study.patient.patient_code)
    metadata.create_study(anonymous, OrganName.LUNG)

    page = metadata.list_history(50, 0, dni_x)

    assert [entry.study_code for entry in page.entries] == [second_x, first_x]
    assert all(entry.national_id == dni_x for entry in page.entries)
    assert page.has_more is False

    [entry] = own_entries(metadata, [anonymous])
    assert entry.national_id is None

    empty = metadata.list_history(50, 0, dni_none)
    assert empty.entries == []
    assert empty.has_more is False
