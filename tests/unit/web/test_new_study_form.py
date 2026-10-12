"""El formulario de nuevo estudio de static/index.html: que campos bloquean el envio.

No hay DOM en estas pruebas (la carpeta web corre sin npm). Se lee el HTML y se aplican
las reglas de validacion de restricciones del estandar HTML con las que el navegador
decide si un formulario se envia: un campo habilitado con required y vacio, o con un
valor que no cumple su pattern o su maxlength, impide el submit, salvo que el
formulario tenga novalidate o el boton formnovalidate.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parents[3] / "src" / "radvol3d" / "static" / "index.html"
FORM_ID = "study-card"
FILLED = {
    "f-code": "RV-20261012-1530",
    "f-patient-name": "Rosaura",
    "f-patient-surname": "Quispecahuana",
    "f-patient-dni": "87654321",
}


class FormParser(HTMLParser):
    """Junta los input del formulario y su boton de envio."""

    def __init__(self) -> None:
        super().__init__()
        self.form: dict[str, str | None] | None = None
        self.inputs: dict[str, dict[str, str | None]] = {}
        self.submit_buttons: list[dict[str, str | None]] = []
        self._inside = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form" and attributes.get("id") == FORM_ID:
            self.form, self._inside = attributes, True
        elif self._inside and tag == "input" and attributes.get("type") not in {"file", "hidden"}:
            self.inputs[attributes["id"]] = attributes
        elif self._inside and tag == "button" and attributes.get("type") == "submit":
            self.submit_buttons.append(attributes)

    def handle_endtag(self, tag: str) -> None:
        if tag == "form" and self._inside:
            self._inside = False


@pytest.fixture(scope="module")
def form() -> FormParser:
    parser = FormParser()
    parser.feed(INDEX_HTML.read_text(encoding="utf-8"))
    assert parser.form is not None, f"falta <form id={FORM_ID!r}> en index.html"
    return parser


def is_valid(field: dict[str, str | None], value: str) -> bool:
    """Una entrada de texto cumple sus restricciones (required, maxlength, pattern)."""
    if "disabled" in field:
        return True
    if "required" in field and value == "":
        return False
    if value == "":
        return True  # maxlength y pattern no se aplican a un valor vacio
    if "maxlength" in field and len(value) > int(field["maxlength"]):
        return False
    pattern = field.get("pattern")
    return pattern is None or re.fullmatch(pattern, value) is not None


def submits(form: FormParser, **values: str) -> bool:
    """El navegador dispara submit con estos valores (los demas campos, como FILLED)."""
    if "novalidate" in form.form or any("formnovalidate" in b for b in form.submit_buttons):
        return True
    filled = FILLED | {key.replace("_", "-"): value for key, value in values.items()}
    return all(is_valid(field, filled.get(field_id, "")) for field_id, field in form.inputs.items())


@pytest.mark.unit
def test_the_form_is_sent_with_a_submit_button_and_browser_validation(form) -> None:
    assert [button["id"] for button in form.submit_buttons] == ["btn-create"]
    assert "novalidate" not in form.form
    assert {"f-code", "f-patient-name", "f-patient-surname", "f-patient-dni"} <= set(form.inputs)
    assert submits(form)


@pytest.mark.unit
def test_an_empty_first_name_does_not_send_the_form(form) -> None:
    assert "required" in form.inputs["f-patient-name"]
    assert not submits(form, f_patient_name="")


@pytest.mark.unit
def test_an_empty_last_name_does_not_send_the_form(form) -> None:
    assert "required" in form.inputs["f-patient-surname"]
    assert not submits(form, f_patient_surname="")


@pytest.mark.unit
def test_an_empty_national_id_still_sends_the_form(form) -> None:
    assert "required" not in form.inputs["f-patient-dni"]
    assert submits(form, f_patient_dni="")


@pytest.mark.unit
@pytest.mark.parametrize("national_id", ["1234567", "1234567A"])
def test_a_national_id_that_is_not_eight_digits_does_not_send_the_form(
    form, national_id: str
) -> None:
    dni = form.inputs["f-patient-dni"]
    assert (dni["maxlength"], dni["placeholder"], dni["inputmode"]) == ("8", "12345678", "numeric")
    assert not submits(form, f_patient_dni=national_id)


@pytest.mark.unit
@pytest.mark.parametrize("code", ["", "con espacio", "rv.0418"])
def test_an_invalid_study_code_does_not_send_the_form(form, code: str) -> None:
    assert not submits(form, f_code=code)
