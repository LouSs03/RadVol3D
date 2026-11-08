"""Pruebas de la admision del DICOM (requisito 9 de la guia del modo de una radiografia)."""

import pytest

from radvol3d import config
from radvol3d.domain.exceptions import InvalidRadiographError, RadiographTooLargeError
from radvol3d.services.pipeline.radiograph_check import is_dicom, validate_radiograph
from tests.fixtures.radiograph_files import fake_dicom


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["placa.dcm", "PLACA.DICOM", "IM0001", None])
def test_a_dicom_with_an_accepted_name_passes(filename: str | None) -> None:
    content = fake_dicom()

    assert validate_radiograph(content, filename) is content


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["informe.pdf", "virus.exe", "notas.txt", "placa.png"])
def test_other_extensions_are_rejected(filename: str) -> None:
    with pytest.raises(InvalidRadiographError, match="DICOM"):
        validate_radiograph(fake_dicom(), filename)


@pytest.mark.unit
def test_a_renamed_file_without_the_dicm_mark_is_rejected() -> None:
    pdf = b"%PDF-1.7" + b"\x00" * 400

    assert not is_dicom(pdf)
    with pytest.raises(InvalidRadiographError, match="DICM"):
        validate_radiograph(pdf, "placa.dcm")


@pytest.mark.unit
def test_an_empty_file_is_rejected() -> None:
    with pytest.raises(InvalidRadiographError, match="vacía"):
        validate_radiograph(b"", "placa.dcm")


@pytest.mark.unit
def test_a_file_over_the_limit_is_too_large(monkeypatch) -> None:
    monkeypatch.setattr(config, "MAX_RADIOGRAPH_BYTES", 2000)

    with pytest.raises(RadiographTooLargeError, match="tamaño máximo"):
        validate_radiograph(fake_dicom(2001), "placa.dcm")
    assert validate_radiograph(fake_dicom(2000), "placa.dcm")


@pytest.mark.unit
def test_the_limit_fits_in_the_free_supabase_bucket() -> None:
    # El bucket gratuito de Supabase no acepta archivos de mas de 50 MB.
    assert config.MAX_RADIOGRAPH_BYTES <= 50_000_000
