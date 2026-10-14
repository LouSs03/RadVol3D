"""Pruebas de scripts/regenerate_organ_meshes.py: simulacion, respaldo y restauracion.

El regenerador es un doble: ninguna prueba abre la base ni el bucket.
"""

import importlib.util
import io
from pathlib import Path

import pytest
import trimesh

from radvol3d.domain.entities import Study
from radvol3d.domain.enums import OrganName, StudyStatus
from radvol3d.services.organ_mesh_regeneration import OrganMeshUpdate

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "regenerate_organ_meshes.py"


def load_script():
    spec = importlib.util.spec_from_file_location("regenerate_organ_meshes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def box_glb(side_mm: float) -> bytes:
    return trimesh.creation.box(extents=(side_mm,) * 3).export(file_type="glb")


OLD = box_glb(200.0)  # 8 L
NEW = box_glb(100.0)  # 1 L


class FakeRegenerator:
    def __init__(self, failing: set[str] | None = None) -> None:
        self.failing = failing or set()
        self.saved: list[tuple[str, bytes]] = []

    def build(self, study: Study) -> OrganMeshUpdate:
        if study.study_code in self.failing:
            raise FileNotFoundError("ruta/interna/secreta.npy")
        return OrganMeshUpdate(study.study_code, study.organ, OLD, NEW)

    def save(self, study_code: str, organ_mesh: bytes) -> None:
        self.saved.append((study_code, organ_mesh))


def studies(*codes: str) -> list[Study]:
    return [Study(study_code=c, organ=OrganName.LUNG, status=StudyStatus.COMPLETED) for c in codes]


@pytest.mark.unit
def test_mesh_liters_measures_the_closed_volume() -> None:
    assert load_script().mesh_liters(OLD) == pytest.approx(8.0)


@pytest.mark.unit
def test_without_apply_nothing_is_saved_or_backed_up(tmp_path: Path) -> None:
    script, regenerator, out = load_script(), FakeRegenerator(), io.StringIO()

    failures = script.regenerate(regenerator, studies("a", "b"), False, tmp_path / "bk", out)

    assert failures == 0
    assert regenerator.saved == []
    assert not (tmp_path / "bk").exists()
    assert "a (lung): 8.00 L -> 1.00 L" in out.getvalue()


@pytest.mark.unit
def test_with_apply_the_old_mesh_is_backed_up_before_the_new_one_is_saved(
    tmp_path: Path,
) -> None:
    script, regenerator = load_script(), FakeRegenerator()
    backup = tmp_path / "bk"

    script.regenerate(regenerator, studies("a"), True, backup, io.StringIO())

    assert (backup / "a_organ.glb").read_bytes() == OLD
    assert regenerator.saved == [("a", NEW)]


@pytest.mark.unit
def test_a_study_that_fails_does_not_stop_the_others_nor_leak_its_message(
    tmp_path: Path,
) -> None:
    script, out = load_script(), io.StringIO()
    regenerator = FakeRegenerator(failing={"b"})

    failures = script.regenerate(regenerator, studies("a", "b", "c"), True, tmp_path, out)

    assert failures == 1
    assert [code for code, _ in regenerator.saved] == ["a", "c"]
    assert "b: no se pudo regenerar (FileNotFoundError)" in out.getvalue()
    assert "secreta" not in out.getvalue()


@pytest.mark.unit
def test_restore_uploads_every_backed_up_mesh(tmp_path: Path) -> None:
    script, regenerator = load_script(), FakeRegenerator()
    (tmp_path / "a_organ.glb").write_bytes(b"glTF-a")
    (tmp_path / "b_organ.glb").write_bytes(b"glTF-b")
    (tmp_path / "otro.txt").write_text("se ignora")

    failures = script.restore(regenerator, tmp_path, io.StringIO())

    assert failures == 0
    assert regenerator.saved == [("a", b"glTF-a"), ("b", b"glTF-b")]


@pytest.mark.unit
def test_restore_from_an_empty_folder_reports_it(tmp_path: Path) -> None:
    out = io.StringIO()

    assert load_script().restore(FakeRegenerator(), tmp_path, out) == 1
    assert "No hay mallas respaldadas" in out.getvalue()
