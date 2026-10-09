"""Comprueba los valores cerrados que agrega la funcionalidad 004."""

import pytest

from radvol3d.domain.enums import ResultFile


@pytest.mark.unit
def test_the_downloadable_result_files_are_exactly_three() -> None:
    assert {item.name: item.value for item in ResultFile} == {
        "ORGAN_MESH": "organ_mesh",
        "TUMOR_MESH": "tumor_mesh",
        "VOLUME": "volume",
    }
