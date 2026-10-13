"""Historial de estudios contra el Supabase de prueba (funcionalidad 005).

La consulta agregada (left join lesion, group by, filtro por DNI) solo se puede probar
contra PostgreSQL. La base de prueba es compartida: cada prueba compara solo sus
propios codigos (prefijo de la sesion) y, al filtrar, DNI generados al azar. Se omite si
no existe .env.test.
"""

from collections.abc import Callable, Iterable

import pytest

from radvol3d.domain.entities import Lesion, StudyHistoryEntry
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
