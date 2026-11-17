"""Pruebas de la particion de los pesos de X2CT-GAN (sin subir nada)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "publish_x2ct_weights.py"


def load_script():
    spec = importlib.util.spec_from_file_location("publish_x2ct_weights", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
def test_118_mb_are_split_in_three_parts_under_45_mb_that_join_back() -> None:
    module = load_script()
    data = bytes(118_103_575)

    parts = module.split(data)

    assert len(parts) == 3
    assert all(len(part) < 45_000_000 for part in parts)
    assert b"".join(parts) == data


@pytest.mark.unit
def test_a_small_file_is_a_single_part() -> None:
    module = load_script()

    assert module.split(b"abc", max_part_bytes=10) == [b"abc"]
