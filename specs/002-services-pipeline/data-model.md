# Data Model: Capa de servicios y tubería de procesamiento

Esta funcionalidad no cambia el esquema de la base: no agrega tablas ni columnas. Lo que
cambia es esto:

- dos campos y dos errores en `domain/`;
- tipos propios de `services/`, que no salen de la capa salvo `ProjectionFile` y
  `StudyRequest`, que construye la presentación;
- un objeto de configuración nuevo en la persistencia;
- las filas que se escriben en `model`.

## 1. Cambios en `domain/`

### `SegmentationResult` (entities.py)

| Campo | Tipo | Cambio | Regla |
|---|---|---|---|
| `mask` | arreglo `(N,N,N)` uint8 | igual | valores en {0, 1} |
| `probability` | arreglo `(N,N,N)` float32 | igual | misma forma que `mask`, valores en [0, 1] |
| `global_confidence` | float | igual | en [0, 1] |
| `lesions` | `list[Lesion]` | igual | una por región de `summary["regions"]` |
| `summary` | `Mapping[str, object]` | **nuevo**, por omisión `{}` | estructura de §4 |

### Errores (exceptions.py)

| Error | Hereda de | Cuándo | Atributos |
|---|---|---|---|
| `StageFailedError` | `RadVol3DError` | una etapa de la tubería lanzó una excepción | `study_code: str`, `stage_number: StageNumber` |
| `StudyInProgressError` | `RadVol3DError` | se pidió borrar un estudio en `processing` | — |

Los errores que ya existen y usa esta capa son `InvalidProjectionError`,
`ModelNotAvailableError`, `StudyNotFoundError`, `DuplicateStudyError`, `InvalidStudyIdError`,
`StorageError` y `DatabaseUnavailableError`.

## 2. Tipos de `services/`

| Tipo | Módulo | Campos | Notas |
|---|---|---|---|
| `ProjectionFile` | `pipeline/projection_loader.py` | `angle_degrees: int`, `content: bytes`, `original_name: str \| None` | lo arma la presentación con cada archivo subido |
| `StudyRequest` | `study_service.py` | `study_code: str`, `organ: OrganName`, `projections: list[ProjectionFile]`, `patient: PatientDetails \| None` | entrada de `process_study` |
| `StrategySet` | `strategy_factory.py` | `reconstruction`, `segmentation`, `meshing` | inmutable; las instancias se comparten entre estudios |
| `MeshSet` | `meshing/meshing_strategy.py` | `organ: bytes`, `tumor: bytes` | dos archivos `.glb` |
| `PipelineData` | `pipeline/pipeline_data.py` | `study_code`, `projections_by_angle`, `projections`, `volume`, `segmentation`, `meshes` | inmutable; cada filtro devuelve una copia con su campo lleno (`dataclasses.replace`) |
| `PipelineProgress` | `pipeline/progress.py` | `Protocol`: `stage_started`, `stage_completed`, `stage_failed`, `save_volume`, `save_result` | puerto hacia la persistencia |
| `ServiceContainer` | `service_container.py` | `study_service`, `factory`, `close()` | vive en `app.state.services` |

### Filtros de la tubería

| Etapa (`StageNumber`) | Filtro | Entrada → salida | Modelo registrado | Guardado después del filtro |
|---|---|---|---|---|
| 1 `PREPROCESSING` | `PreprocessingFilter` | `projections_by_angle` → `projections (4,128,128) float32` | — | — |
| 2 `RECONSTRUCTION` | `ReconstructionFilter` | `projections` → `volume (128,128,128) float32 [0,1]` | el de la estrategia | `save_volume` |
| 3 `SEGMENTATION` | `SegmentationFilter` | `volume` → `segmentation: SegmentationResult` | el de la estrategia | — |
| 4 `MESHING` | `MeshingFilter` | `volume`, `segmentation.mask` → `meshes: MeshSet` | — | `save_result` |

## 3. Transiciones de estado

### Estudio (`StudyStatus`)

```text
            register_study           start_processing
  (nada) ─────────────────► pending ─────────────────► processing
                                                         │
                         complete_study ◄─── 4 etapas ok ┤
                               │                         │ una etapa falla
                               ▼                         ▼
                           completed                   failed
```

- `delete_study` acepta `pending`, `completed` y `failed`. Con `processing` lanza
  `StudyInProgressError`.
- Una entrada inválida (admisión) o un modelo no disponible fallan antes de
  `register_study`, así que no hay estudio.

### Etapa (`StageStatus`)

```text
waiting ──stage_started──► running ──stage_completed──► completed
   │                          │
   │                          └──stage_failed(n)──► failed
   └── stage_failed(m < n) ──► skipped
```

- `stage_failed(n)` deja, en una sola unidad de trabajo, la etapa `n` en `failed`, las
  etapas `> n` en `skipped` y el estudio en `failed`.
- `started_at` se registra solo al pasar a `running`. `finished_at` se registra al pasar a
  `completed`, `failed` o `skipped`, como ya hace el repositorio.

## 4. Resumen de segmentación (`summary.json`)

Tiene las mismas claves que `models/ejemplo_resumen.json`. La estrategia EN-2 alinea con el
dominio solo los identificadores (FR-025). Los números no cambian.

| Clave | Lo que da el módulo original | Lo que guarda el sistema |
|---|---|---|
| `study_id` | lo que reciba `id_estudio` | se reemplaza por `study_code`, con el código del estudio |
| `organ` | `datos["organo"]` o `"pulmon"` | `"lung"` (`OrganName.LUNG`) |
| `model_name` | `datos["nombre_modelo"]` o `"segmentacion_pulmon"` | `"segmentation_lung"` (el de la estrategia) |
| `model_version` | `datos["version"]` o `"1.0.0"` | el de la estrategia (`"1.0.0"`) |
| `threshold`, `mm_per_voxel`, `grid`, `has_lesion`, `lesion_count`, `global_confidence`, `total_volume_mm3` | calculados | sin cambios |
| `regions[]` | ver abajo | sin cambios |
| `location_note` | texto en español | sin cambios |

Cada elemento de `regions` se convierte en una `Lesion` y en una fila de `lesion`:

| Región | `Lesion` / columna | Regla |
|---|---|---|
| `location` | `location` | texto en español, geométrico |
| `volume_mm3` | `volume_mm3` | > 0 |
| `max_diameter_mm` | `max_diameter_mm` | ≥ 0 |
| `confidence` | `confidence` | en [0, 1] |
| — | `mesh_path` | `<study_code>/meshes/tumor.glb` |
| `has_lesion`, `voxels`, `centroid_voxel`, `confidence_min`, `confidence_max`, `region_id` | — | solo en `summary.json` |

## 5. Filas de `model` que escribe esta funcionalidad

| `model_name` | `version` | `trained_on` | `description` | Etapas que lo usan |
|---|---|---|---|---|
| `reconstruction_en1` | `1.0.0` | `NULL`, `TODO(TRAINING_DATE_EN1)` | retroproyector de TA-2, filtro rampa y U-Net 3D residual EN-1 | 2 |
| `segmentation_lung` | `1.0.0` | `NULL`, `TODO(TRAINING_DATE_EN2)` | U-Net 3D residual con supervisión profunda EN-2 | 3; también `study.model_id` |

- La versión `1.0.0` de EN-2 viene de `cfg.version_modelo` del punto de control. La de EN-1 es
  la etiqueta que ya tenía la estrategia, porque su `.pth` no trae versión.
- Los dobles se registran como `fake_reconstruction 0.0.0` y `fake_segmentation 0.0.0`, pero
  solo en la base de prueba.
- Las etapas 1 y 4 no tienen modelo.

## 6. Configuración nueva (`persistence/settings.py`)

`ModelSettings` se carga con `get_model_settings()`. Ningún campo es obligatorio: si falta
uno, el modelo correspondiente queda no disponible, no se detiene el arranque.

| Variable | Campo | Por omisión | Uso |
|---|---|---|---|
| `MODEL_BUCKET` | `model_bucket: str \| None` | `None` | bucket de pesos y referencias |
| `EN1_WEIGHTS_OBJECT` | `en1_weights_object: str \| None` | `None` | ruta del `.pth` de EN-1 en el bucket |
| `EN2_WEIGHTS_OBJECT` | `en2_weights_object: str \| None` | `None` | ruta del `.pth` de exportación de EN-2 |
| `MODEL_CACHE_DIR` | `model_cache_dir: Path` | `.cache/models` | caché local de pesos (en `.gitignore`) |
| `RECONSTRUCTION_STRATEGY` | `reconstruction_strategy: str` | `"en1"` | clave del registro de reconstrucción |

Usa las mismas credenciales de Supabase que `Settings`, sin duplicar la clave.

## 7. Rutas del bucket que se borran (`delete_study`)

Son las diez de `storage_layout`:

- `projections/angle_000.npy`, `angle_045.npy`, `angle_090.npy` y `angle_135.npy`
- `volume.npy`
- `segmentation/mask.npy`, `segmentation/probability.npy` y `segmentation/summary.json`
- `meshes/organ.glb` y `meshes/tumor.glb`

Todas cuelgan de `<study_code>/`. Si una ruta ya no existe, no es un error.
