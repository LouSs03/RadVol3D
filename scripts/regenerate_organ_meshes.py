#!/usr/bin/env python3
"""Regenera la malla del organo de los estudios ya procesados, sin volver a procesarlos.

Los estudios procesados antes de un cambio en la region del organo conservan la malla
vieja (docs/models/meshing.md). Este script la rehace desde el volumen guardado, con la
misma estrategia que usaria hoy la tuberia. No carga EN-1, EN-2 ni torch.

Solo cambia meshes/organ.glb. El tumor, las lesiones, sus filas y el resumen quedan
como estan.

Seguro por omision:

- Sin --apply es una simulacion: calcula y muestra el volumen de la malla vieja y el de
  la nueva, y no escribe nada.
- Con --apply, antes de reemplazar cada malla guarda la vieja en --backup-dir
  (por omision .cache/organ_mesh_backup/<fecha-hora>).
- --restore <carpeta> vuelve a subir las mallas de un respaldo.

Lee las credenciales de --env-file (por omision .env). No imprime claves.

Uso:
    python scripts/regenerate_organ_meshes.py                      # simulacion
    python scripts/regenerate_organ_meshes.py --apply              # respalda y reemplaza
    python scripts/regenerate_organ_meshes.py --apply --study RV-20261012-1530
    python scripts/regenerate_organ_meshes.py --restore .cache/organ_mesh_backup/<carpeta>
"""

import argparse
import io
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import TextIO

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

import trimesh  # noqa: E402 - despues de ajustar sys.path

from radvol3d.domain.entities import Study  # noqa: E402
from radvol3d.persistence.connection import Database  # noqa: E402
from radvol3d.persistence.object_storage import ObjectStorage  # noqa: E402
from radvol3d.persistence.result_store import ResultStore  # noqa: E402
from radvol3d.persistence.settings import ModelSettings, Settings  # noqa: E402
from radvol3d.persistence.study_metadata_store import StudyMetadataStore  # noqa: E402
from radvol3d.services.organ_mesh_regeneration import OrganMeshRegenerator  # noqa: E402
from radvol3d.services.service_container import default_strategy_builders  # noqa: E402
from radvol3d.services.strategy_factory import StrategyFactory  # noqa: E402

BACKUP_ROOT = REPOSITORY_ROOT / ".cache" / "organ_mesh_backup"
BACKUP_SUFFIX = "_organ.glb"


def mesh_liters(glb: bytes) -> float:
    """Volumen encerrado por la malla, en litros (las mallas estan en mm)."""
    scene = trimesh.load(io.BytesIO(glb), file_type="glb")
    return sum(abs(geometry.volume) for geometry in scene.geometry.values()) / 1e6


def regenerate(
    regenerator: OrganMeshRegenerator,
    studies: Sequence[Study],
    apply: bool,
    backup_dir: Path,
    out: TextIO,
) -> int:
    """Rehace la malla de cada estudio. Devuelve cuantos fallaron (sigue con el resto)."""
    failures = 0
    for study in studies:
        try:
            update = regenerator.build(study)
            line = (
                f"{update.study_code} ({update.organ.value}): "
                f"{mesh_liters(update.previous):.2f} L -> {mesh_liters(update.current):.2f} L"
            )
            if apply:
                backup_dir.mkdir(parents=True, exist_ok=True)
                (backup_dir / f"{update.study_code}{BACKUP_SUFFIX}").write_bytes(update.previous)
                regenerator.save(update.study_code, update.current)
                line += "  reemplazada"
            print(line, file=out)
        except Exception as error:  # noqa: BLE001 - un estudio que falla no frena a los demas
            failures += 1
            # Solo el tipo: el texto puede traer rutas internas del bucket.
            print(f"{study.study_code}: no se pudo regenerar ({type(error).__name__})", file=out)
    return failures


def restore(regenerator: OrganMeshRegenerator, backup_dir: Path, out: TextIO) -> int:
    """Vuelve a subir las mallas de un respaldo. Devuelve cuantas fallaron."""
    failures = 0
    backups = sorted(backup_dir.glob(f"*{BACKUP_SUFFIX}"))
    if not backups:
        print(f"No hay mallas respaldadas en {backup_dir}.", file=out)
        return 1
    for path in backups:
        study_code = path.name.removesuffix(BACKUP_SUFFIX)
        try:
            regenerator.save(study_code, path.read_bytes())
            print(f"{study_code}: malla restaurada", file=out)
        except Exception as error:  # noqa: BLE001 - igual que en regenerate
            failures += 1
            print(f"{study_code}: no se pudo restaurar ({type(error).__name__})", file=out)
    return failures


def build_regenerator(env_file: Path) -> tuple[OrganMeshRegenerator, Database]:
    """Arma el regenerador con la base, el bucket y solo las estrategias de mallas."""
    settings = Settings(_env_file=env_file)
    model_settings = ModelSettings(_env_file=env_file)
    database = Database.from_settings(settings)
    database.open()
    storage = ObjectStorage.from_settings(settings)
    builders = default_strategy_builders(None, model_settings)
    factory = StrategyFactory(
        reconstruction_builders={},
        segmentation_builders={},
        meshing_builder=builders.meshing,
        reconstruction_key=model_settings.reconstruction_strategy,
        organ_meshing_builders=builders.organ_meshing,
    )
    factory.preload()
    regenerator = OrganMeshRegenerator(
        StudyMetadataStore(database, storage), ResultStore(database, storage), factory
    )
    return regenerator, database


def main(argv: list[str] | None = None, out: TextIO = sys.stdout) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", type=Path, default=REPOSITORY_ROOT / ".env")
    parser.add_argument("--apply", action="store_true", help="respalda y reemplaza las mallas")
    parser.add_argument(
        "--study", action="append", default=[], help="solo este estudio (se puede repetir)"
    )
    parser.add_argument("--backup-dir", type=Path, default=None)
    parser.add_argument("--restore", type=Path, default=None, help="carpeta de un respaldo")
    args = parser.parse_args(argv)

    regenerator, database = build_regenerator(args.env_file)
    try:
        if args.restore is not None:
            return 1 if restore(regenerator, args.restore, out) else 0
        studies = regenerator.completed_studies()
        if args.study:
            wanted = set(args.study)
            studies = [study for study in studies if study.study_code in wanted]
            missing = wanted - {study.study_code for study in studies}
            for code in sorted(missing):
                print(f"{code}: no existe o no esta terminado; se omite", file=out)
        backup_dir = args.backup_dir or BACKUP_ROOT / datetime.now().strftime("%Y%m%d-%H%M%S")
        print(
            f"{len(studies)} estudios terminados. "
            + (f"Respaldo en {backup_dir}" if args.apply else "Simulacion: no se escribe nada."),
            file=out,
        )
        failures = regenerate(regenerator, studies, args.apply, backup_dir, out)
        if not args.apply and studies:
            print("Para aplicar: agrega --apply.", file=out)
        return 1 if failures else 0
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
