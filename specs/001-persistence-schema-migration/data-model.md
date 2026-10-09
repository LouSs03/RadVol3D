# Data Model: Migración de la capa de persistencia

La fuente de verdad del esquema es `docs/database/schema/001_create_tables.sql`. Este documento
describe cómo se corresponden las tablas con las entidades del dominio, qué se valida y qué
estados existen.

## Entidades del dominio (`domain/entities.py`)

Ninguna entidad lleva ids seriales, salvo `Organ.organ_id`, que ya existía (research.md, R4).

### Patient (nueva)

| Campo | Tipo | Origen | Notas |
|---|---|---|---|
| `patient_code` | `str` | `patient.patient_code` | `^PAC[0-9]{6}$` para los pacientes nuevos |
| `first_name` | `str \| None` | `patient.first_name` | `repr=False` |
| `last_name` | `str \| None` | `patient.last_name` | `repr=False` |
| `national_id` | `str \| None` | `patient.national_id` | `repr=False`; ocho dígitos |

### PatientDetails (nueva, de entrada)

Son los datos personales que llegan de la interfaz: `first_name`, `last_name` y `national_id`.
Los tres son opcionales y se declaran con `repr=False`. Si los tres están vacíos, o en blanco
después de quitar espacios, el estudio se asocia a `PAC000000`.

### Model (nueva)

| Campo | Tipo | Origen |
|---|---|---|
| `model_name` | `str` | `model.model_name` |
| `version` | `str` | `model.version` |
| `trained_on` | `date \| None` | `model.trained_on` (solo si se conoce) |
| `description` | `str \| None` | `model.description` |

### Study (se modifica)

| Campo | Tipo | Origen | Cambio |
|---|---|---|---|
| `study_code` | `str` | `study.study_code` | — |
| `organ` | `OrganName` | `organ.name` (por `organ_id`) | — |
| `status` | `StudyStatus` | `study.status` | — |
| `patient` | `Patient \| None = None` | `patient` (por `patient_id`) | **nuevo** |
| `model` | `Model \| None = None` | `model` (por `model_id`) | **nuevo** |
| `grid_size` | `int \| None = None` | `study.grid_size` | **nuevo** |
| `created_at` | `datetime \| None` | `study.created_at` | — |
| `total_time_sec` | `float \| None` | `study.total_time_sec` | — |
| `projections` | `list[Projection]` | `projection` | — |
| `stages` | `list[ProcessingStage]` | `processing_stage` | — |
| `lesions` | `list[Lesion]` | `lesion` | — |

Los campos nuevos van después de los que ya existían y tienen valor por defecto. Así no se
rompen las construcciones actuales.

### ProcessingStage (se modifica)

Se agrega `model: Model | None = None`, que sale de `processing_stage.model_id`. `stage_name` no
es un campo: se deriva de `stage_number` (research.md, R9).

### Projection, Lesion y Organ

No cambian. Sus campos ya coinciden con las columnas.

### StoredResult (nueva)

Es lo que devuelve `result_store`. Campos:

| Campo | Tipo | Valor si el estudio aún no tiene resultado |
|---|---|---|
| `study_code` | `str` | el código consultado |
| `lesions` | `list[Lesion]` | lista vacía |
| `mask_path` | `str \| None` | `None` |
| `probability_path` | `str \| None` | `None` |
| `summary_path` | `str \| None` | `None` |
| `organ_mesh_path` | `str \| None` | `None` |
| `tumor_mesh_path` | `str \| None` | `None` |

Un estudio tiene resultado guardado cuando sus etapas 3 y 4 están en `completed`. Si no es así,
el resultado es vacío. Un estudio con resultado guardado y sin lesiones (`regions: []`) tiene
las cinco rutas y la lista de lesiones vacía: no es lo mismo que no tener resultado.

## Correspondencia con las tablas

| Tabla | Repositorio | Entidad | Clave natural |
|---|---|---|---|
| `patient` | `PatientRepository` | `Patient` | `patient_code`; `national_id` cuando existe |
| `organ` | `OrganRepository` | `Organ` | `name` |
| `model` | `ModelRepository` | `Model` | `(model_name, version)` |
| `study` | `StudyRepository` | `Study` | `study_code` |
| `projection` | `ProjectionRepository` | `Projection` | `(study_code, angle_degrees)` |
| `processing_stage` | `ProcessingStageRepository` | `ProcessingStage` | `(study_code, stage_number)` |
| `lesion` | `LesionRepository` | `Lesion` | ninguna; se agrupan por `study_code` |

## Validaciones

Las validaciones de esta tabla se hacen en el código **antes** de tocar la base o el bucket.
Las restricciones del esquema siguen activas como última defensa.

| Regla | Dónde | Error |
|---|---|---|
| Código de estudio `^[A-Za-z0-9_-]{1,64}$`; sin `..`, barra invertida ni cadena vacía | `storage_layout` | `InvalidStudyIdError` |
| Ángulo en {0, 45, 90, 135} | `storage_layout`, `projection_repository` | `InvalidProjectionError` |
| Cuatro ángulos distintos al registrar | `study_metadata_store` | `InvalidProjectionError` |
| DNI de exactamente ocho dígitos | `patient_repository` | `InvalidPatientDataError` |
| Código de paciente nuevo `^PAC[0-9]{6}$`; no pasa de `PAC999999` | `patient_repository` | `PatientCodeExhaustedError` |
| Órgano `lung` o `liver` | `organ_repository` (búsqueda por nombre) | `UnknownOrganError` |
| `volume_mm3 > 0`; `0 ≤ confidence ≤ 1`; claves obligatorias de cada región | `result_store`, `lesion_repository` | `InvalidLesionError` |
| `finished_at` no anterior a `started_at` | `processing_stage_repository` | `PersistenceError` |
| Variables de entorno presentes y no vacías | `settings` | `ConfigurationError` |

## Restricciones y errores del dominio

`database_errors.py` traduce cada restricción del esquema a un error del dominio. Los nombres
`*_key` y `*_fkey` no están escritos en el SQL: son los que PostgreSQL genera por convención.
**Confirmados el 2026-10-09 contra el catálogo (`pg_constraint`) del Supabase de prueba:** los diez
nombres de esta tabla existen, con el tipo esperado (unique o check). Las demás restricciones del
esquema (claves foráneas, `study_status_allowed`, `stage_*`, `organ_*`, `model_name_version_unique`,
`study_total_time_positive`) no tienen error propio y caen en `PersistenceError`.

| Restricción | Clase de psycopg | Error del dominio |
|---|---|---|
| `study_study_code_key` | `UniqueViolation` | `DuplicateStudyError` |
| `study_code_format` | `CheckViolation` | `InvalidStudyIdError` |
| `patient_national_id_format`, `patient_national_id_key`, `patient_code_format`, `patient_patient_code_key` | `CheckViolation` / `UniqueViolation` | `InvalidPatientDataError` |
| `projection_angle_allowed`, `projection_study_angle_unique` | `CheckViolation` / `UniqueViolation` | `InvalidProjectionError` |
| `lesion_volume_positive`, `lesion_confidence_range` | `CheckViolation` | `InvalidLesionError` |
| `model_name_version_unique` | `UniqueViolation` | no debería ocurrir: el alta usa `on conflict` (FR-027) |
| cualquier otra violación de integridad | `IntegrityError` | `PersistenceError` |
| sin conexión o grupo agotado | `OperationalError`, `PoolTimeout` | `DatabaseUnavailableError` |

### Errores nuevos en `domain/exceptions.py`

Todos heredan de `RadVol3DError`, salvo uno que hereda de `StorageError`, como se indica.

| Error | Cuándo |
|---|---|
| `ConfigurationError` | falta una variable o está vacía |
| `DuplicateStudyError` | el código de estudio ya existe |
| `InvalidPatientDataError` | DNI con formato inválido |
| `PatientCodeExhaustedError` | el siguiente código pasaría de `PAC999999` |
| `UnknownOrganError` | órgano fuera del alcance |
| `InvalidLesionError` | una lesión o una región viola una regla |
| `PersistenceError` | violación de integridad sin traducción específica, o falta de datos iniciales |
| `StorageObjectNotFoundError` (hereda de `StorageError`) | el archivo no existe en el bucket |

Todos los mensajes van en español y nunca incluyen valores de credenciales ni datos personales.

## Estados

### Estudio (`study.status`)

```text
pending ──► processing ──► completed
                 │
                 └──────► failed
```

- `pending` es el estado al registrar el estudio.
- Al pasar a `completed` se registran a la vez `model`, `grid_size` y `total_time_sec`
  (FR-033).
- La capa no impone el orden de las transiciones: lo decide la tubería. La capa solo acepta los
  cuatro valores del enumerado.

### Etapa (`processing_stage.stage_status`)

```text
waiting ──► running ──► completed | failed
   │
   └──────────────────► skipped | completed | failed   (sin started_at)
```

- **`running`:** registra `started_at`.
- **`completed`, `skipped` y `failed`:** registran `finished_at`.
- **Etapas 3 y 4:** `result_store` las pasa a `completed` en la misma unidad de trabajo en que
  guarda las lesiones.

## Archivos del bucket por estudio

| Archivo | Ruta | Lo escribe | Tipo de contenido |
|---|---|---|---|
| Proyecciones | `<study_code>/projections/angle_000.npy` … `angle_135.npy` | `study_metadata_store` | `application/octet-stream` |
| Volumen | `<study_code>/volume.npy` | `study_metadata_store` | `application/octet-stream` |
| Máscara | `<study_code>/segmentation/mask.npy` | `result_store` | `application/octet-stream` |
| Probabilidad | `<study_code>/segmentation/probability.npy` | `result_store` | `application/octet-stream` |
| Resumen | `<study_code>/segmentation/summary.json` | `result_store` | `application/json` |
| Malla del órgano | `<study_code>/meshes/organ.glb` | `result_store` | `model/gltf-binary` |
| Malla del tumor | `<study_code>/meshes/tumor.glb` | `result_store` | `model/gltf-binary` |

La ruta `<study_code>/meshes/lesion_<region_id>.glb` está reservada y no se genera (FR-051).
