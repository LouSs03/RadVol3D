# Contrato: artefactos de los modelos

Este contrato cubre los archivos que viven fuera de git y que el sistema y las pruebas `ml`
necesitan: los pesos, el `.pth` de exportación de EN-2 y la referencia de regresión.

## Bucket de modelos (`MODEL_BUCKET`)

```text
reconstruction_en1/1.0.0/weights.pth        # copia sin cambios de models/en1_pesos_liviano (2).pth
segmentation_lung/1.0.0/weights.pth         # salida de scripts/export_en2_weights.py
regression/en1_phantom_projections.npy      # entrada del caso 1 (4,128,128) float32
regression/en1_phantom_volume.npy           # salida de referencia del caso 1 (128,128,128) float32
regression/en2_gaussian_mask.npy            # caso 2: máscara uint8
regression/en2_gaussian_probability.npy     # caso 2: probabilidad float32
regression/en2_gaussian_summary.json        # caso 2: resumen
regression/en2_from_en1_mask.npy            # caso 3: EN-2 sobre la salida del caso 1
regression/en2_from_en1_probability.npy
regression/en2_from_en1_summary.json
```

`EN1_WEIGHTS_OBJECT` y `EN2_WEIGHTS_OBJECT` apuntan a las dos primeras rutas. El bucket es
privado y se lee con la misma clave de servicio que el bucket de datos.

## `.pth` de exportación de EN-2

Lo genera `scripts/export_en2_weights.py` una sola vez. El script lee
`models/en2_pulmon_mejor.pth` (punto de control) y `models/metricas_test.json` (métricas).

| Clave | Tipo | Fuente |
|---|---|---|
| `pesos` | `state_dict` | `punto_de_control["modelo"]`, sin cambios |
| `canales` | `list[int]` | `punto_de_control["canales"]`, hoy `[16, 32, 64, 128, 192]` |
| `parche` | `int` | `punto_de_control["cfg"]["parche"]`, hoy 96 |
| `rejilla` | `int` | `punto_de_control["cfg"]["rejilla"]`, hoy 128 |
| `mm_por_voxel` | `float` | 2,5 (`config.MM_PER_VOXEL`) |
| `umbral` | `float` | `metricas_test["umbral"]`, hoy 0,3 |
| `min_voxeles` | `int` | `metricas_test["min_voxeles"]`, hoy 10 |
| `tta` | `bool` | `metricas_test["tta"]`, hoy `true` |

Los opcionales (`solape`, `supervision`, `ventana_hu`, `organo`, `nombre_modelo`, `version`)
no se escriben, así que el módulo usa sus valores por omisión.

El archivo debe poder abrirse con `torch.load(..., weights_only=True)`. Si llega el `.pth` de
exportación original, se sube a la misma ruta y se regenera la referencia de EN-2.

## Manifiesto de regresión (`tests/ml/reference/manifest.json`, versionado)

```json
{
  "generated_on": "<fecha ISO en que se corrió el script>",
  "generator": "scripts/generate_regression_reference.py",
  "sources": {"en1": "en1_inferencia_nuevo (1).py", "en2": "en2_inferencia.py"},
  "environment": {"torch": "…", "numpy": "…", "scipy": "…", "platform": "…", "device": "cpu"},
  "tolerance": {"mask": "exact", "volume_abs": 1e-5, "probability_abs": 1e-5},
  "cases": [
    {
      "name": "en1_phantom",
      "input": {"recipe": "proyectar(fantoma_elipsoide()) con sus valores por omision",
                "object": "regression/en1_phantom_projections.npy", "sha256": "…"},
      "outputs": [{"object": "regression/en1_phantom_volume.npy", "sha256": "…",
                   "shape": [128, 128, 128], "dtype": "float32"}]
    }
  ]
}
```

Los valores `…` los escribe el script; no se rellenan a mano. Las pruebas `ml` bajan cada
objeto, comprueban su SHA-256 y comparan con la tolerancia. Si el entorno difiere del
manifiesto, lo dicen en el mensaje de fallo.
