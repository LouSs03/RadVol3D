"""Pruebas del armado del .pth de exportacion de EN-2 (Q1 = B; research.md R18).

Solo prueban build_export_payload, que no usa torch: el script se carga por ruta.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "export_en2_weights.py"


def load_script():
    spec = importlib.util.spec_from_file_location("export_en2_weights", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATE = {"entrada.c1.weight": "tensor"}
CHECKPOINT = {
    "modelo": STATE,
    "epoca": 160,
    "dice_val": 0.7527,
    "canales": [16, 32, 64, 128, 192],
    "cfg": {"parche": 96, "rejilla": 128, "mm_por_voxel": 2.5, "solape_ventana": 0.5},
}
METRICS = {"umbral": 0.3, "min_voxeles": 10, "tta": True, "dice_test": 0.6553}


@pytest.mark.unit
def test_the_payload_has_exactly_the_eight_keys_and_their_sources() -> None:
    payload = load_script().build_export_payload(CHECKPOINT, METRICS)

    assert payload == {
        "pesos": STATE,
        "canales": [16, 32, 64, 128, 192],
        "parche": 96,
        "rejilla": 128,
        "mm_por_voxel": 2.5,
        "umbral": 0.3,
        "min_voxeles": 10,
        "tta": True,
    }
    assert payload["pesos"] is STATE  # los tensores no se copian ni se tocan


@pytest.mark.unit
def test_the_optional_keys_are_left_to_the_module_defaults() -> None:
    payload = load_script().build_export_payload(CHECKPOINT, METRICS)

    for key in ("solape", "supervision", "ventana_hu", "organo", "nombre_modelo", "version"):
        assert key not in payload


@pytest.mark.unit
@pytest.mark.parametrize(
    ("source", "key"),
    [("checkpoint", "modelo"), ("checkpoint", "canales"), ("metrics", "umbral"), ("metrics", "tta")],
)
def test_a_missing_source_key_is_named(source: str, key: str) -> None:
    checkpoint, metrics = dict(CHECKPOINT), dict(METRICS)
    del (checkpoint if source == "checkpoint" else metrics)[key]

    with pytest.raises(KeyError, match=key):
        load_script().build_export_payload(checkpoint, metrics)


@pytest.mark.unit
def test_a_missing_cfg_key_is_named() -> None:
    checkpoint = dict(CHECKPOINT, cfg={"rejilla": 128})

    with pytest.raises(KeyError, match="parche"):
        load_script().build_export_payload(checkpoint, METRICS)


@pytest.mark.unit
def test_importing_the_script_does_not_import_torch() -> None:
    import sys

    already = "torch" in sys.modules
    load_script()

    assert already or "torch" not in sys.modules
