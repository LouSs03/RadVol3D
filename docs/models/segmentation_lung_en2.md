# Modelo de segmentación de pulmón EN-2

| | |
|---|---|
| Entrada | `(128, 128, 128)` float32 en [0, 1], misma ventana HU que la reconstrucción |
| Salida | máscara uint8, probabilidad float32 en [0, 1] y resumen por región (`models/ejemplo_resumen.json`) |
| Arquitectura | U-Net 3D residual con supervisión profunda, canales `[16, 32, 64, 128, 192]`, parches de 96 con TTA de 8 volteos |
| Conjunto | Medical Segmentation Decathlon, Task06_Lung |
| Registro en `model` | `segmentation_lung`, versión `1.0.0` (de `cfg.version_modelo`) |
| Fecha de entrenamiento | `TODO(TRAINING_DATE_EN2)`: no está en los pesos ni en el repositorio; `trained_on` queda vacío |

## Dónde vive cada cosa

- **Código.**
  - `src/radvol3d/services/segmentation/lung_region_summary.py`: ventanas, limpieza y resumen, solo numpy y scipy.
  - `lung_unet_network.py`: la red.
  - `lung_segmenter.py`: carga e inferencia.
  - `lung_unet_strategy.py`: la estrategia.

  Todo se migró de `models/en2_inferencia.py` sin cambiar la lógica. Los atributos de la
  red que forman las claves del `state_dict` conservan su nombre original.
- **Pesos.** Bucket de modelos, `segmentation_lung/1.0.0/weights.pth`. Es el `.pth` de
  exportación que genera `scripts/export_en2_weights.py`.
- **Carga.** `torch.load(..., weights_only=True)`. El original usaba `weights_only=False`.

## Procedencia del `.pth` de exportación (decisión Q1 = B)

`models/en2_pulmon_mejor.pth` es un punto de control de entrenamiento, con las claves
`modelo`, `epoca`, `dice_val`, `cfg` y `canales`. El segmentador exige otras claves en el
primer nivel. El script las arma así, sin tocar los tensores:

| Clave | Fuente |
|---|---|
| `pesos` | `punto_de_control["modelo"]` |
| `canales` | `punto_de_control["canales"]` |
| `parche`, `rejilla` | `punto_de_control["cfg"]` (96 y 128) |
| `mm_por_voxel` | 2,5 (`config.MM_PER_VOXEL`) |
| `umbral`, `min_voxeles`, `tta` | `models/metricas_test.json` (0,3, 10 y `true`) |

Si llega el `.pth` de exportación original, se sube a la misma ruta sin cambiar código y
se regenera la referencia de EN-2.

## Resumen y lesiones

La estrategia alinea con el dominio solo los identificadores del resumen:

- `study_id` pasa a `study_code`;
- `organ` pasa a `lung`;
- `model_name` y `model_version` pasan a los de la tabla `model`.

Los números no cambian. Los textos `location` y `location_note` siguen en español y
describen una posición geométrica por tercios de cada eje, no un lóbulo anatómico. Cada
elemento de `regions` se guarda como una fila de `lesion`.

## Métricas (copiadas de `models/metricas_test.json`)

Se citan para documentar el modelo. Esta funcionalidad no las volvió a medir.

| Métrica | Valor |
|---|---|
| Dice de validación | 0,7361 |
| Dice de prueba | 0,6553 ± 0,2771 |
| Precisión de prueba | 0,6628 |
| Sensibilidad de prueba | 0,804 |
| Casos de entrenamiento, validación y prueba | 44, 9 y 10 |
| Umbral, mínimo de vóxeles y TTA | 0,3, 10 y sí |
| Entrenamiento | 200 épocas configuradas y ejecutadas; mejor época, 160 |
| Reproducibilidad | Dice original 0,6553 y recargado 0,6553 (diferencia 0,0) |

Protocolo, según el mismo archivo: volúmenes remuestreados a 2,50 mm por vóxel en una
rejilla de 128³, ventana HU [-1000, 1000].

## Referencia de comparación

Carles, M., Kuhn, D., Fechter, T., et al. (2024). Development and evaluation of two
open-source nnU-Net models for automatic segmentation of lung tumors on PET and CT images.
*European Radiology*, 34(10), 6701-6711. DOI: 10.1007/s00330-024-10751-2

Dice de referencia: 0,63 ± 0,34 sobre tomografía computarizada real (intervalo [0,29;
0,97]). Según `metricas_test.json`, el Dice de prueba cae dentro del intervalo.

## Diferencias de protocolo que hay que declarar

La referencia usa tomografía diagnóstica a resolución completa y entrenamiento
multicéntrico. Aquí se trabaja con volúmenes remuestreados a 2,5 mm por vóxel y con un
conjunto de entrenamiento mucho menor.

Además, en el sistema el segmentador recibe un volumen **reconstruido**, no una tomografía
real. Medir cuánto cae el Dice en ese paso es la brecha 3 del estado del arte, y ningún
trabajo revisado lo ha cuantificado.

## Tiempo

Con el `.pth` de exportación, en CPU con 4 hilos y TTA, una segmentación tardó ≈ 148 s en
la laptop de desarrollo (2026-10-09). Dos corridas seguidas dieron la misma probabilidad
bit a bit. Es una medición de referencia, no una meta.
