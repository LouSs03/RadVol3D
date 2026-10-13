"""Historial de estudios contra el Supabase de prueba (funcionalidad 005).

La consulta agregada (left join lesion, group by, filtro por DNI) solo se puede probar
contra PostgreSQL. La base de prueba es compartida: cada prueba compara solo sus
propios codigos (prefijo de la sesion) y, al filtrar, DNI generados al azar. Se omite si
no existe .env.test.
"""

from collections.abc import Callable, Iterable

import pytest

from radvol3d.domain.entities import StudyHistoryEntry
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.persistence.connection import Database
from radvol3d.persistence.object_storage import ObjectStorage
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
