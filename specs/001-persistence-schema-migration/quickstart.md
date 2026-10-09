# Quickstart: validar la capa de persistencia

Esta guía explica cómo comprobar que la funcionalidad cumple la especificación. Las firmas están
en [contracts/persistence_api.md](contracts/persistence_api.md) y las reglas, en
[data-model.md](data-model.md).

## Requisitos

- `.venv` con `pip install -r requirements-dev.txt`. Debe incluir `psycopg[binary,pool]`.
- Para las pruebas de integración, un `.env.test` copiado de `.env.test.example` que apunte a un
  proyecto de Supabase **de prueba** con `001_create_tables.sql` aplicado y su bucket creado.
  Las pruebas de integración nunca leen `.env`.

## 1. Lo que corre antes de cada commit (sin red)

```text
pytest -m "unit or architecture"
ruff check src tests
python scripts/check_naming_convention.py
```

Resultado esperado: todo en verde. Las pruebas de `tests/unit/persistence/` deben pasar con la
red desconectada (SC-004). Además, `test_layer_boundaries.py` debe pasar sin modificarse
(SC-008).

## 2. Escenarios unitarios por componente

| Componente | Qué demuestra la prueba | Requisitos |
|---|---|---|
| settings | Sin `SUPABASE_SERVICE_KEY`, lanza `ConfigurationError` y el mensaje nombra la variable. Los secretos no aparecen en `str`, `repr` ni en el mensaje. | FR-007 a FR-009, SC-006 |
| connection | `open()` abre el grupo una sola vez. `transaction()` confirma o revierte. Si el grupo no abre, lanza `DatabaseUnavailableError`. | FR-010 a FR-012 |
| database_errors | Cada restricción de [data-model.md](data-model.md#restricciones-y-errores-del-dominio) produce su error del dominio, sin el texto ni la causa de psycopg. | FR-003, FR-025 |
| storage_layout | Las siete rutas son exactas. Rechaza `..`, la barra invertida, la cadena vacía y los ángulos inválidos. | FR-013 a FR-017 |
| object_storage | Un arreglo sale igual que entró. Un `.npy` con objetos se rechaza. Si el archivo no existe, lanza `StorageObjectNotFoundError`. Subir a una ruta ocupada la reemplaza. `from_settings` mantiene la clave fuera de los registros DEBUG. | FR-018 a FR-021, SC-003 |
| patient_repository | Un DNI nuevo crea `PAC…+1`, un DNI conocido reutiliza el paciente y sin datos se usa `PAC000000`. Rechaza un DNI de siete dígitos. Pasar de `PAC999999` es un error. | FR-022 a FR-025, SC-007 |
| organ_repository | Devuelve `lung` y `liver`. Un órgano desconocido lanza `UnknownOrganError`. | FR-026 |
| model_repository | El mismo par registrado dos veces da un solo modelo. | FR-027 a FR-029 |
| study_repository | Código duplicado lanza `DuplicateStudyError`, código inexistente lanza `StudyNotFoundError`, y `mark_completed` registra los tres datos. | FR-030 a FR-034 |
| projection_repository | Las proyecciones vuelven ordenadas por ángulo. Rechaza ángulos inválidos o repetidos. | FR-035 a FR-037 |
| processing_stage_repository | Prepara cuatro etapas en `waiting` sin duplicarlas y registra las horas al cambiar de estado. | FR-038 a FR-040 |
| lesion_repository | Rechaza el lote entero si una lesión es inválida. | FR-041 a FR-043 |
| study_metadata_store | Registra todo como una unidad. Con un código duplicado no sube ningún archivo. `save_volume` de un estudio inexistente lanza `StudyNotFoundError` y no sube nada. | FR-044 a FR-046 |
| result_store | Tres regiones dan tres filas, una lista `regions` vacía da cero filas y las etapas 3 y 4 quedan en `completed`. Si falla, las etapas no cambian. `get_result` sobre un estudio sin resultado devuelve rutas en `None` y lesiones vacías, sin error. Solo un estudio inexistente lanza `StudyNotFoundError`. | FR-047 a FR-050 |

## 3. Integración contra el Supabase de prueba

```text
pytest -m integration tests/integration/persistence
```

Resultado esperado: el recorrido completo pasa contra la base y el bucket reales. Los estudios
usan el prefijo `it_` y se borran al final.

- Se registra un estudio con DNI, se guarda el volumen y un resultado con dos regiones, y se
  lee de nuevo. Todo vuelve con los mismos valores (SC-001).
- Dos registros con el mismo DNI producen un solo paciente (SC-007).
- Dos registros simultáneos sin DNI reciben códigos distintos.

**Confirmado el 2026-10-09** contra el Supabase de prueba (T056):

- Los nombres de las restricciones `*_key` generados por PostgreSQL coinciden con los de
  [data-model.md](data-model.md).
- Al bajar un objeto inexistente, Supabase lanza `StorageApiError` (404, `not_found`), subclase de
  `StorageException` (research.md, R7).

## 4. Comprobaciones manuales de la especificación

- **SC-002:** buscar `paciente|estudio|proyeccion|etapa_procesamiento|lesion_detectada|modelo|organo`
  en los **identificadores** (variables, funciones, clases, argumentos) y en las **sentencias SQL**
  de `src/radvol3d/persistence`. Debe dar cero coincidencias. Un `grep` literal sobre todo el texto
  da coincidencias que no cuentan: los mensajes de error y los docstrings están en español y
  mencionan "estudio", "modelo" u "organo". Conviene revisar con `ast`, no con `grep`.
- **SC-003:** buscar en la salida de la suite (`pytest -m "unit or integration" -rA`) los valores
  de `.env.test`, un DNI de prueba y un nombre de prueba. Deben aparecer cero veces.
