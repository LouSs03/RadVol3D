#!/usr/bin/env python3
"""Genera, una sola vez, el .pth de exportacion de EN-2 que espera el segmentador.

Por que existe: models/en2_pulmon_mejor.pth es un punto de control de entrenamiento
(claves modelo, epoca, dice_val, cfg y canales). El segmentador de pulmon, migrado
sin cambios desde models/en2_inferencia.py, exige otras claves en el primer nivel.
Este script arma ese archivo sin entrenar nada y sin tocar los tensores (decision
Q1 = B de specs/002-services-pipeline).

De donde sale cada clave del archivo generado:

    pesos        <- punto_de_control["modelo"]          (los mismos tensores)
    canales      <- punto_de_control["canales"]
    parche       <- punto_de_control["cfg"]["parche"]
    rejilla      <- punto_de_control["cfg"]["rejilla"]
    mm_por_voxel <- 2.5 (config.MM_PER_VOXEL: 320 mm / 128 voxeles)
    umbral       <- metricas_test["umbral"]
    min_voxeles  <- metricas_test["min_voxeles"]
    tta          <- metricas_test["tta"]

Las claves opcionales (solape, supervision, ventana_hu, organo, nombre_modelo,
version) no se escriben: el segmentador usa sus valores por omision, que coinciden
con cfg (solape_ventana 0.5, supervision 3).

Si mas adelante llega el .pth de exportacion original, se sube en lugar de este a la
misma ruta del bucket, sin cambiar codigo, y se regenera la referencia de EN-2 con
scripts/generate_regression_reference.py.

Uso:
    python scripts/export_en2_weights.py \\
        --checkpoint models/en2_pulmon_mejor.pth \\
        --metrics models/metricas_test.json \\
        --output .cache/models/segmentation_lung/1.0.0/weights.pth
"""

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

# 320 mm de campo de vision sobre 128 voxeles (src/radvol3d/config.py).
MM_PER_VOXEL = 2.5


def build_export_payload(checkpoint: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict:
    """Arma el diccionario del .pth de exportacion. No usa torch ni copia tensores.

    Si falta una clave de origen, lanza KeyError con su nombre.
    """
    cfg = _required(checkpoint, "cfg")
    return {
        "pesos": _required(checkpoint, "modelo"),
        "canales": _required(checkpoint, "canales"),
        "parche": _required(cfg, "parche"),
        "rejilla": _required(cfg, "rejilla"),
        "mm_por_voxel": MM_PER_VOXEL,
        "umbral": _required(metrics, "umbral"),
        "min_voxeles": _required(metrics, "min_voxeles"),
        "tta": _required(metrics, "tta"),
    }


def _required(source: Mapping[str, Any], key: str) -> Any:
    if key not in source:
        raise KeyError(f"Falta la clave '{key}' en el archivo de origen.")
    return source[key]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--metrics", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    import torch  # solo aqui: el resto del modulo se prueba sin torch

    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    metrics = json.loads(args.metrics.read_text(encoding="utf-8"))
    payload = build_export_payload(checkpoint, metrics)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.save(payload, args.output)
    reloaded = torch.load(args.output, map_location="cpu", weights_only=True)
    if set(reloaded) != set(payload):
        print("El archivo generado no se pudo volver a abrir completo.", file=sys.stderr)
        return 1
    print(f"Exportacion de EN-2 escrita en {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
