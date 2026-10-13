# Data Model: Historial de estudios persistente

La base no cambia: no hay migración ni columnas nuevas (research.md R2). Lo nuevo son dos
tipos del dominio, una consulta y los esquemas de la API.

## 1. Tablas que se leen (sin cambios)

| Tabla | Columnas que usa el historial | Notas |
|---|---|---|
| `study` | `study_id`, `study_code`, `status`, `created_at`, `organ_id`, `patient_id` | `study_id` solo desempata el orden y no sale de la persistencia |
| `organ` | `name` | `lung` o `liver` |
| `patient` | `national_id` | Ocho dígitos, opcional y único (índice por la restricción `unique`) |
| `lesion` | `lesion_id`, `study_id`, `volume_mm3` | `volume_mm3 > 0`, `numeric(12, 2)` |

Nombre y apellido (`patient.first_name`, `patient.last_name`) **no se leen** en esta
consulta.

## 2. Dominio (`src/radvol3d/domain/entities.py`)

### `StudyHistoryEntry` (nuevo, `frozen=True`)

| Campo | Tipo | Regla |
|---|---|---|
| `study_code` | `str` | Formato `^[A-Za-z0-9_-]{1,64}$` |
| `organ` | `OrganName` | |
| `status` | `StudyStatus` | Estado guardado en este momento (FR-003) |
| `created_at` | `datetime \| None` | |
| `lesion_count` | `int \| None` | `None` si `status` no es `completed` (R4). Si es `completed`, ≥ 0 |
| `total_lesion_volume_mm3` | `float \| None` | `None` si no es `completed`. Si lo es, es la suma de `lesion.volume_mm3`, o `0.0` sin lesiones |
| `national_id` | `str \| None` | `repr=False`. `None` cuando el paciente no tiene DNI, incluido el de referencia `PAC000000` |

### `StudyHistoryPage` (nuevo, `frozen=True`)

| Campo | Tipo | Regla |
|---|---|---|
| `entries` | `list[StudyHistoryEntry]` | Como máximo `limit` elementos, del más reciente al más antiguo |
| `offset` | `int` | ≥ 0 |
| `limit` | `int` | Entre 1 y 100 |
| `has_more` | `bool` | `true` si existe al menos un estudio después de esta página |

## 3. Persistencia

### `StudyRepository.list_history(limit, offset, national_id=None) -> list[StudyHistoryEntry]`

- Hace una sola consulta (R2). Si `national_id` no es `None`, filtra por
  `patient.national_id`.
- Revalida el DNI con `NATIONAL_ID_PATTERN` (`patient_repository.py`). Si no cumple, lanza
  `InvalidPatientDataError("El DNI debe tener exactamente ocho digitos.")`, sin el valor.
- Devuelve los conteos tal como están en la base. No aplica la regla de `completed`, que
  le toca al servicio (R4).
- Convierte `numeric` a `float`.

### `StudyMetadataStore.list_history(limit, offset, national_id=None) -> StudyHistoryPage`

- Abre la transacción y le pide al repositorio `limit + 1` filas.
- Arma la página: corta a `limit` y calcula `has_more` (R3).

## 4. Servicios

### `StudyService.list_history(limit, offset, national_id=None) -> StudyHistoryPage`

- Delega en el almacén.
- Pone `lesion_count` y `total_lesion_volume_mm3` en `None` en cada entrada cuyo estado no
  es `completed` (R4).
- No contiene condicionales por órgano.

## 5. API (`src/radvol3d/api/schemas/history_schema.py`)

### `StudyHistoryItem`

Los mismos campos que `StudyHistoryEntry`, con los mismos nombres. Es la única respuesta de
la API que lleva `national_id` (R8). No tiene `first_name` ni `last_name`.

### `StudyHistoryResponse`

`items: list[StudyHistoryItem]`, `offset`, `limit`, `has_more`.

### `StudySearchRequest` (`hide_input_in_errors=True`)

| Campo | Regla |
|---|---|
| `national_id` | Obligatorio, `^[0-9]{8}$`. Se quitan los espacios de los extremos antes de validar |
| `offset` | Opcional, ≥ 0, por defecto 0 |
| `limit` | Opcional, entre 1 y 100, por defecto 50 |

## 6. Estados y valores mostrados

| `status` | `lesion_count` | `total_lesion_volume_mm3` | En la página |
|---|---|---|---|
| `pending`, `processing`, `failed` | `null` | `null` | "—" en Lesiones y en Volumen |
| `completed`, sin lesiones | `0` | `0.0` | "0" y "Sin lesiones" |
| `completed`, con lesiones | `n ≥ 1` | `> 0` | `n` y `format_volume(total)` (R5) |

| `national_id` | En la página |
|---|---|
| ocho dígitos | Los ocho dígitos, completos (FR-010) |
| `null` | "sin DNI" |
