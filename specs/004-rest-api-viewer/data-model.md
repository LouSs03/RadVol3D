# Data Model: Capa de API REST y visor 3D

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

Tres niveles: la base (una columna nueva), el dominio (campos y tipos nuevos) y los esquemas
HTTP de `api/schemas/`. Los esquemas HTTP no son entidades del dominio: son la forma de lo
que entra y sale por la red.

---

## 1. Base de datos

### `lesion` (cambia)

Migración `docs/database/schema/002_add_lesion_organ.sql` (research.md R11).

| Columna | Tipo | Nulo | Cambio | Regla |
|---|---|---|---|---|
| `organ` | `varchar(32)` | no | **nueva** | `lesion_organ_allowed`: `organ in ('lung', 'liver')`. La llena el insert con el `organ.name` del estudio. |
| `mesh_path` | `text` | sí | **cambia su contenido** | Hoy apunta a `<study_code>/meshes/tumor.glb` en todas las filas. Pasa a apuntar a `<study_code>/meshes/lesion_<NNN>.glb`, una por fila (R10). |

Sin `region_id`: sigue solo en `summary.json`. Las demás columnas no cambian.

### Bucket de datos

| Ruta | Cambio |
|---|---|
| `<study_code>/meshes/lesion_<NNN>.glb` | **nueva**. Una por lesión. `NNN` = posición de la región en el resumen, desde `001`. |
| `organ.glb`, `tumor.glb`, `volume.npy` y el resto | sin cambios |

---

## 2. Dominio (`domain/`)

### `Lesion` (cambia)

| Campo | Tipo | Cambio |
|---|---|---|
| `organ` | `OrganName \| None` | **nuevo**, por omisión `None`. Lo llena la persistencia al leer. Las estrategias no lo llenan. |
| `mesh_path` | `str \| None` | sin cambio de tipo; ahora cada lesión tiene su propia ruta |

### `StoredResult` (cambia)

| Campo | Tipo | Cambio |
|---|---|---|
| `volume_path` | `str \| None` | **nuevo**. `None` en un resultado vacío. |

### `ResultFile` (nuevo, `domain/enums.py`)

`StrEnum` con los archivos únicos de un resultado que se pueden bajar:
`ORGAN_MESH = "organ_mesh"`, `TUMOR_MESH = "tumor_mesh"`, `VOLUME = "volume"`. Las mallas
por lesión no entran aquí: se piden por número.

### Error nuevo (`domain/exceptions.py`)

| Error | Cuándo |
|---|---|
| `InvalidStudyStateError` (nuevo) | La operación no corresponde al estado del estudio: subir proyecciones a un estudio que ya las tiene o no está `pending`; procesar uno sin proyecciones o que no está `pending`; pedir el resultado o un archivo de uno que no está `completed`. El mensaje dice el estado actual y la operación, sin datos del paciente. |

`StudyInProgressError` (borrado rechazado) se mantiene como está.

---

## 3. Servicios (`services/`)

### `MeshSet` (cambia)

| Campo | Tipo | Cambio |
|---|---|---|
| `organ` | `bytes` | sin cambio |
| `tumor` | `bytes` | sin cambio |
| `lesions` | `tuple[bytes, ...]` | **nuevo**. Un `.glb` por región con lesión, en el orden del resumen. Vacío si no hay lesiones. |

### Regiones de lesión

`split_lesion_masks(mask, regions) -> list[ndarray]` (R9). Entrada: la máscara y las regiones
del resumen con `has_lesion` verdadero; cada región trae `voxels` y `centroid_voxel`. Salida:
una máscara booleana por región. Lanza `ValueError` si una región no tiene su componente.

---

## 4. Estados

### Estudio

```text
            POST /studies                POST /process (claim)
  (nada) ───────────────► pending ─────────────────────────► processing
                            │  ▲                                │    │
     POST /projections      │  │ (sigue en pending:             │    │ tubería
     (una vez, si no tiene) └──┘  solo gana proyecciones)       │    │ termina
                                                                │    ▼
                        tubería falla, o el servidor arranca    │  completed
                        con el estudio en processing (R5)       ▼
                                                              failed

  DELETE: permitido en pending, completed y failed; 409 en processing.
```

| Operación | `pending` sin proyecciones | `pending` con 4 proyecciones | `processing` | `completed` | `failed` |
|---|---|---|---|---|---|
| subir proyecciones | ✅ | 409 | 409 | 409 | 409 |
| procesar | 409 | ✅ → `processing` | 409 | 409 | 409 |
| estado | ✅ | ✅ | ✅ | ✅ | ✅ |
| resultado y descargas | 409 | 409 | 409 | ✅ | 409 |
| visor | estado | estado | estado (se refresca) | escena | etapa que falló |
| borrar | ✅ | ✅ | 409 | ✅ | ✅ |

### Etapas

Sin cambios respecto de 002 (`waiting` → `running` → `completed`, o `failed` y las
siguientes `skipped`). La recuperación al arrancar (R5) usa esa misma regla.

---

## 5. Esquemas HTTP (`api/schemas/`)

Todos los campos en inglés y snake_case. Ninguno trae nombre, apellido ni DNI en una
respuesta.

### `study_schema.py`

**`PatientInput`** (entrada, opcional dentro de `StudyCreate`)

| Campo | Tipo | Regla |
|---|---|---|
| `first_name` | `str \| None` | hasta 80 caracteres |
| `last_name` | `str \| None` | hasta 80 caracteres |
| `national_id` | `str \| None` | 8 dígitos (la persistencia vuelve a validar) |

**`StudyCreate`** (entrada de `POST /studies`)

| Campo | Tipo | Regla |
|---|---|---|
| `study_code` | `str` | `^[A-Za-z0-9_-]{1,64}$` |
| `organ` | `OrganName` | `lung` o `liver` |
| `patient` | `PatientInput \| None` | opcional |

**`StudyResponse`** (salida de `POST /studies`)

| Campo | Tipo |
|---|---|
| `study_code` | `str` |
| `organ` | `OrganName` |
| `status` | `StudyStatus` |
| `created_at` | `datetime` |
| `patient_code` | `str \| None` |

**`StageStatusResponse`**

| Campo | Tipo |
|---|---|
| `stage_number` | `int` (1 a 4) |
| `stage_name` | `str` (`preprocessing`, `reconstruction`, `segmentation`, `meshing`) |
| `status` | `StageStatus` |
| `started_at` | `datetime \| None` |
| `finished_at` | `datetime \| None` |

**`StudyStatusResponse`** (salida de `GET /status`): los campos de `StudyResponse`, más
`total_time_sec: float | None` y `stages: list[StageStatusResponse]` (siempre cuatro, en
orden).

**`ProcessingAccepted`** (salida de `POST /process`): `study_code`, `status`
(`processing`) y `status_url` (`/studies/{code}/status`).

### `projection_schema.py`

**`ProjectionsUploaded`** (salida de `POST /projections`): `study_code` y
`angles: list[int]` (`[0, 45, 90, 135]`). La entrada son los cuatro campos de archivo de
research.md R7; no tiene esquema de Pydantic.

### `result_schema.py`

**`LesionResponse`**

| Campo | Tipo | Nota |
|---|---|---|
| `lesion_number` | `int` | posición en la lista, desde 1 |
| `organ` | `OrganName` | de la columna `lesion.organ` |
| `location` | `str` | texto en español |
| `volume_mm3` | `float` | |
| `max_diameter_mm` | `float \| None` | |
| `confidence` | `float` | 0 a 1 |
| `mesh_url` | `str` | `/studies/{code}/result/lesions/{n}.glb` |

Sin `region_id` ni `lesion_id`.

**`ResultResponse`** (salida de `GET /result`)

| Campo | Tipo |
|---|---|
| `study_code` | `str` |
| `organ_mesh_url` | `str` |
| `tumor_mesh_url` | `str` |
| `volume_url` | `str` |
| `lesions` | `list[LesionResponse]` |

### `error_schema.py`

**`ErrorResponse`**: `detail: str`. **`ValidationErrorResponse`**:
`detail: list[{loc, msg, type}]`, sin `input` (research.md R8).
