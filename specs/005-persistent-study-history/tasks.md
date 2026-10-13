---

description: "Lista de tareas: historial de estudios persistente con volumen de lesión y DNI"
---

# Tasks: Historial de estudios persistente con volumen de lesión y DNI

**Input**: Design documents from `/specs/005-persistent-study-history/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md),
[data-model.md](data-model.md), [contracts/http_api_history.md](contracts/http_api_history.md),
[contracts/internal_changes.md](contracts/internal_changes.md), [quickstart.md](quickstart.md)

**Tests**: se incluyen. Las exigen el Principio IV de la constitución (prueba unitaria en el
mismo pull request) y FR-015 a FR-017 de la spec. En cada componente, la prueba se escribe
antes que el código y debe fallar.

**Organization**: las tareas se agrupan por historia de la spec:

- **US1 (P1)**: ver todos los estudios guardados desde cualquier navegador;
- **US2 (P1)**: ver el volumen de lesión de cada estudio;
- **US3 (P2)**: identificar al paciente por su DNI y filtrar por él.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: se puede hacer en paralelo (archivos distintos, sin depender de tareas sin terminar)
- **[Story]**: historia de la spec a la que pertenece la tarea (US1 a US3)
- Todas las rutas son relativas a la raíz del repositorio

## Path Conventions

Proyecto único (ver "Structure Decision" en [plan.md](plan.md)):

- **Código**: `src/radvol3d/{domain,persistence,services,api,static}/` y
  `src/radvol3d/main.py`.
- **Pruebas**:
  - `tests/unit/` (marca `unit`);
  - `tests/unit/web/*.js` (`node --test`);
  - `tests/integration/persistence/` (marca `integration`).
- **Dobles**:
  - `tests/fixtures/fake_database.py`: `FakeConnection` y `FakeCursor`;
  - `tests/fixtures/fake_container.py`: `study_service` es un
    `create_autospec(StudyService)`, así que `list_history` tiene que existir en
    `StudyService` antes de las pruebas del router.

Reglas de todas las tareas:

- **Nombres** (Principio III): identificadores, rutas HTTP, campos JSON y columnas en inglés
  y snake_case, también en JavaScript. Comentarios, docstrings y mensajes al usuario en
  español.
- **Capas** (Principio I): `api/` no importa `persistence`, `psycopg`, `supabase` ni `torch`.
  `tests/architecture/test_layer_boundaries.py` no se modifica.
- **Datos personales**:
  - nombre y apellido no salen en ninguna respuesta (FR-009);
  - el DNI solo sale en `GET /studies` y `POST /studies/search`;
  - el DNI nunca aparece en registros, mensajes de error, URL, `localStorage` ni consola
    (FR-012).
- **Pruebas `unit`**: ninguna usa la red, la base, el bucket real ni `torch`.
- **Antes de cada commit**: `pytest -m "unit or architecture"`, `ruff check src tests`,
  `python scripts/check_naming_convention.py` y `node --test "tests/unit/web/*.js"`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: rama y documentos de diseño versionados

- [X] T001 Crear la rama `feat/persistent-study-history` desde `feat/rest-api-viewer` (`git switch -c feat/persistent-study-history`)
- [X] T002 Versionar `specs/005-persistent-study-history/` (spec.md, plan.md, research.md, data-model.md, quickstart.md, contracts/, checklists/, tasks.md) con el commit `docs(specs): agrega la especificacion y el plan del historial persistente`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: tipos del dominio y la consulta del historial, desde la base hasta el servicio y
los esquemas de la API. Las tres historias la usan.

**⚠️ CRITICAL**: ninguna historia empieza hasta terminar esta fase

- [ ] T003 [P] Agregar a `tests/unit/domain/test_entities.py` las pruebas de `StudyHistoryEntry` y `StudyHistoryPage`:
  - `repr(StudyHistoryEntry(..., national_id="12345678"))` no contiene `"12345678"`, como `test_patient_representation_hides_personal_data`;
  - las dos son `frozen` (asignar un campo lanza `FrozenInstanceError`);
  - `StudyHistoryPage` guarda `entries`, `offset`, `limit` y `has_more`.
- [ ] T004 Agregar `StudyHistoryEntry` y `StudyHistoryPage` (`@dataclass(frozen=True)`) en `src/radvol3d/domain/entities.py`, según [data-model.md §2](data-model.md):
  - `StudyHistoryEntry` tiene `study_code: str`, `organ: OrganName`, `status: StudyStatus`, `created_at: datetime | None`, `lesion_count: int | None`, `total_lesion_volume_mm3: float | None` y `national_id: str | None = field(default=None, repr=False)`;
  - `StudyHistoryPage` tiene `entries: list[StudyHistoryEntry]`, `offset: int`, `limit: int` y `has_more: bool`;
  - los docstrings van en español.
- [ ] T005 [P] Agregar a `tests/unit/persistence/repositories/test_study_repository.py` las pruebas de `StudyRepository.list_history`, con un ayudante `history_row(**overrides)` que tiene `study_code`, `status`, `created_at`, `organ_name`, `national_id`, `lesion_count` y `total_volume_mm3` (`Decimal`):
  - **Sin DNI**:
    - la sentencia contiene `left join lesion`, `group by` y `order by s.created_at desc, s.study_id desc`;
    - los parámetros son `(limit, offset)`.
  - **Con `national_id="12345678"`**:
    - la sentencia contiene `p.national_id = %s`;
    - los parámetros son `("12345678", limit, offset)`.
  - **Tipos**:
    - `Decimal("42.75")` sale como `42.75` (`float`);
    - `lesion_count` sale como `int`;
    - `organ` sale como `OrganName` y `status` como `StudyStatus`.
  - **Sin filtrar por estado**: los conteos se devuelven tal como vienen, también para `pending` y `failed`.
  - **Sin nombre ni apellido**: la sentencia no menciona `first_name` ni `last_name`.
  - **DNI inválido** (`"1234567"`, `"123456789"`, `"1234567a"`): lanza `InvalidPatientDataError`, el texto del error no contiene el valor y `connection.calls == []`.
  - **Sin filas**: devuelve `[]`.
- [ ] T006 Implementar `StudyRepository.list_history(limit: int, offset: int, national_id: str | None = None) -> list[StudyHistoryEntry]` en `src/radvol3d/persistence/repositories/study_repository.py` (research.md R2):
  - **Consulta**: una sola.
    - Selecciona `s.study_code, s.status, s.created_at, o.name as organ_name, p.national_id`, `count(l.lesion_id) as lesion_count` y `coalesce(sum(l.volume_mm3), 0) as total_volume_mm3`.
    - Une `from study s join organ o on o.organ_id = s.organ_id join patient p on p.patient_id = s.patient_id left join lesion l on l.study_id = s.study_id`.
    - Agrega `where p.national_id = %s` solo si hay DNI.
    - Termina con `group by s.study_id, o.name, p.national_id order by s.created_at desc, s.study_id desc limit %s offset %s`.
  - **Validación**: revalida el DNI con `NATIONAL_ID_PATTERN.fullmatch`, importado de `patient_repository.py`, y si no cumple lanza `InvalidPatientDataError("El DNI debe tener exactamente ocho digitos.")` antes de tocar la base.
  - **Ejecución**: usa `execute_translated`.
- [ ] T007 [P] Agregar a `tests/unit/persistence/test_study_metadata_store.py` las pruebas de `StudyMetadataStore.list_history`, con el doble `world` de `test_list_studies_returns_the_studies_without_nested_data` y una regla para `"left join lesion"`:
  - pide `limit + 1` filas (el parámetro de `limit` en la sentencia es `limit + 1`);
  - con `limit + 1` filas devuelve `has_more=True` y solo `limit` entradas;
  - con `limit` filas o menos devuelve `has_more=False`;
  - `offset` y `limit` vuelven tal como se pidieron;
  - el `national_id` llega al repositorio.
- [ ] T008 Implementar `StudyMetadataStore.list_history(limit: int, offset: int, national_id: str | None = None) -> StudyHistoryPage` en `src/radvol3d/persistence/study_metadata_store.py`, que abre `self._database.transaction()`, llama a `StudyRepository(connection).list_history(limit + 1, offset, national_id)` y arma la página (research.md R3). `list_studies` y `list_recent` no se tocan.
- [ ] T009 [P] Agregar a `tests/unit/services/test_study_service.py` las pruebas de `StudyService.list_history`, con `Harness`:
  - delega en `harness.metadata.list_history` con `(limit, offset, national_id)`;
  - los valores por defecto son `limit=50`, `offset=0` y `national_id=None`;
  - pone `lesion_count=None` y `total_lesion_volume_mm3=None` en las entradas `pending`, `processing` y `failed`, incluso si el almacén trajo `3` y `120.5`;
  - conserva `0` y `0.0` en un `completed` sin lesiones;
  - conserva los valores de un `completed` con lesiones;
  - conserva `national_id`, `offset`, `limit` y `has_more`.
- [ ] T010 Implementar `StudyService.list_history(limit: int = 50, offset: int = 0, national_id: str | None = None) -> StudyHistoryPage` en `src/radvol3d/services/study_service.py` (research.md R4):
  - aplica `dataclasses.replace(entry, lesion_count=None, total_lesion_volume_mm3=None)` a cada entrada cuyo `status is not StudyStatus.COMPLETED`;
  - no tiene condicionales por órgano.
- [ ] T011 [P] Crear `tests/unit/api/test_history_schema.py`:
  - **`StudySearchRequest` válida**:
    - acepta `"12345678"`;
    - quita los espacios de `"  12345678 "`;
    - sin `offset` ni `limit` usa `0` y `50`.
  - **`StudySearchRequest` inválida**:
    - `"1234567"`, `"123456789"`, `"1234567a"`, `""` y la ausencia del campo lanzan `ValidationError`, y `str(error)` no contiene el valor enviado;
    - `limit=0`, `limit=101` y `offset=-1` lanzan `ValidationError`.
  - **Respuesta sin datos personales**: `StudyHistoryItem.model_fields` no tiene `first_name`, `last_name` ni `patient_code`.
- [ ] T012 Crear `src/radvol3d/api/schemas/history_schema.py` ([data-model.md §5](data-model.md)):
  - **`StudyHistoryItem`**: `study_code: str`, `organ: OrganName`, `status: StudyStatus`, `created_at: datetime | None`, `lesion_count: int | None`, `total_lesion_volume_mm3: float | None` y `national_id: str | None`, cada uno con `Field(description=...)` en español.
  - **`StudyHistoryResponse`**: `items: list[StudyHistoryItem]`, `offset: int`, `limit: int` y `has_more: bool`.
  - **`StudySearchRequest`**:
    - `model_config = ConfigDict(hide_input_in_errors=True)`;
    - `national_id: str = Field(pattern=r"^[0-9]{8}$")`, con un `field_validator(mode="before")` que hace `strip()`;
    - `offset: int = Field(default=0, ge=0)`;
    - `limit: int = Field(default=50, ge=1, le=100)`.
  - **Constantes**: `HISTORY_DEFAULT_LIMIT = 50` y `HISTORY_MAX_LIMIT = 100`.
  - **Función**: `history_response(page: StudyHistoryPage) -> StudyHistoryResponse`.

**Checkpoint**: `pytest -m unit` en verde. La consulta, la regla de `completed` y los esquemas existen, sin ruta HTTP todavía.

---

## Phase 3: User Story 1 - Ver todos los estudios guardados desde cualquier navegador (Priority: P1) 🎯 MVP

**Goal**: el historial sale de `GET /studies`, es el mismo en cualquier navegador y no usa
`localStorage`. Conserva las columnas actuales: fecha, estudio y órgano, estado, lesiones y
hallazgo.

**Independent Test**: crear un estudio desde un navegador y abrir el historial en otro, o en
una ventana privada. El estudio aparece con su estado actual (quickstart.md §3, pasos 1 a 3)
y la prueba de integración de T020 pasa.

### Tests for User Story 1 ⚠️

- [ ] T013 [P] [US1] Crear `tests/unit/api/test_history_router.py` con las pruebas de `GET /studies`, usando las fixtures `client` y `service` (`client.app.state.services.study_service`):
  - **Respuesta básica**: responde 200 con `items`, `offset`, `limit` y `has_more`, y los `items` en el mismo orden que la página del servicio.
  - **Parámetros**:
    - sin parámetros llama a `service.list_history.assert_called_once_with(limit=50, offset=0, national_id=None)`;
    - `?offset=50&limit=100` llega tal cual.
  - **Rangos inválidos**: `limit=0`, `limit=101` y `offset=-1` responden 422 sin llamar al servicio.
  - **Página vacía**: devuelve `items: []`.
  - **Datos personales**: ningún item tiene las claves `first_name` ni `last_name`.
  - **Base caída**: `DatabaseUnavailableError` responde 503.
- [ ] T014 [P] [US1] Crear `tests/unit/web/test_history_view.js`, con `node:test` y `node:assert/strict` como `test_viewer_state.js`, para lo de US1:
  - `lesion_count_text({status: "completed", lesion_count: 2})` devuelve `"2"`;
  - `{status: "completed", lesion_count: 0}` da `"0"`;
  - `pending`, `processing` y `failed`, con `lesion_count: null`, dan `"—"`;
  - las constantes `HISTORY_PAGE_SIZE === 50` y `LEGACY_HISTORY_KEY === "radvol3d.history.v1"` existen.

### Implementation for User Story 1

- [ ] T015 [US1] Crear `src/radvol3d/api/routers/history_router.py`:
  - `router = APIRouter(prefix="/studies", tags=["historial"])`;
  - `GET ""` con `offset: int = Query(0, ge=0)` y `limit: int = Query(HISTORY_DEFAULT_LIMIT, ge=1, le=HISTORY_MAX_LIMIT)`, que recibe `StudyService` con `Depends(get_study_service)` y devuelve `history_response(service.list_history(limit=limit, offset=offset, national_id=None))`;
  - `response_model=StudyHistoryResponse` y un `summary` en español;
  - el docstring del módulo explica por qué la URL nunca lleva DNI (research.md R1).
- [ ] T016 [US1] Montar el router en `src/radvol3d/main.py`: importar `history_router` en el bloque de `radvol3d.api.routers` y agregar `app.include_router(history_router.router)` junto a los demás, antes de los `app.mount`.
- [ ] T017 [US1] Crear `src/radvol3d/static/js/history_view.js`:
  - es un módulo ES con funciones puras, en snake_case y sin DOM ni `fetch`;
  - exporta `HISTORY_PAGE_SIZE = 50`, `LEGACY_HISTORY_KEY = "radvol3d.history.v1"` y `lesion_count_text(entry)`, que devuelve `String(entry.lesion_count)` si `entry.status === "completed"` y es un número, y `"—"` si no;
  - lleva un comentario de cabecera que remite a research.md R7.
- [ ] T018 [US1] Reescribir la vista de historial en `src/radvol3d/static/index.html`:
  - **Import**: `import { HISTORY_PAGE_SIZE, LEGACY_HISTORY_KEY, lesion_count_text } from '/static/js/history_view.js';` al inicio del `<script type="module">`. La ruta es absoluta para que funcione en `/static` y en `/static/`.
  - **Estado**: un objeto en memoria, `history_state = { entries: [], has_more: false, loading: false, error: null }`.
  - **Carga**: `load_history(reset)` pide `GET /studies?offset=<n>&limit=HISTORY_PAGE_SIZE` con el `api()` existente.
    - Con `reset`, reemplaza las entradas; si no, las agrega.
    - Un token descarta respuestas viejas, como `history_token`.
  - **Dibujo**: `render_history()` dibuja las filas desde `history_state.entries`.
    - Usa `lesion_count_text` en la columna Lesiones.
    - Muestra un botón "Ver más" (`#h-more`) solo si `has_more`.
  - **Error** (FR-014): vacía las filas y muestra "No se pudo cargar el historial." con un botón "Reintentar", que llama a `load_history(true)`.
  - **Textos**:
    - el estado vacío dice "Todavía no hay estudios en el sistema";
    - el párrafo de cabecera dice "Todos los estudios guardados, del más reciente al más antiguo.".
  - **Navegación**: `route()` llama a `load_history(true)` al entrar en `history`.
- [ ] T019 [US1] Quitar el historial local de `src/radvol3d/static/index.html` (research.md R6):
  - **Funciones**: borrar `HISTORY_KEY`, `read_history`, `write_history`, `remember` y `forget`, y cada llamada a ellas (hoy en `enter_new` al retomar, en la creación, en el procesamiento, en `load_study` y en el borrado). También el estado `deleted` de `STATUS_TAGS`.
  - **Clave vieja**: al arrancar, `try { localStorage.removeItem(LEGACY_HISTORY_KEY); } catch { /* sin almacenamiento */ }`.
  - **Visor**: `latest_completed_code()` pasa a ser `async`. Pide `GET /studies?limit=HISTORY_PAGE_SIZE` y devuelve el `study_code` del primer item `completed`, o `null`. `enter_viewer` hace `await` antes de decidir si muestra el estado vacío.
  - **Abrir una fila**: `open_history_entry(code)` busca en `history_state.entries`. Si es `completed`, va al visor; si es `pending`, a `new`; en otro estado, a `run`.
    - Si la consulta posterior del estudio responde 404, muestra "Este estudio ya no existe." y llama a `load_history(true)`.
  - **Borrar una fila**: tras un `DELETE` con 204 o 404, quita la entrada de `history_state.entries` y vuelve a dibujar, sin recargar la página.
  - **Comentario de privacidad**: actualizar el de la cabecera del script. El historial viene del servidor y el formulario sigue sin guardar nada en el navegador.
- [ ] T020 [US1] Crear `tests/integration/persistence/test_study_history_integration.py` (`@pytest.mark.integration`, fixtures `database`, `object_storage`, `make_study_code` y `created_patient_codes` de `tests/integration/conftest.py`). Primera prueba:
  - **Preparación**: crea 3 estudios con `StudyMetadataStore.create_study` y con códigos de la sesión.
  - **Orden y estado**: recorre `store.list_history(limit=100, offset=n)` hasta encontrar los 3 códigos.
    - La base de prueba es compartida: compara solo el orden relativo de los códigos propios, del más reciente al más antiguo.
    - Comprueba que `status` es `pending`.
  - **Borrado**: tras `store.delete_study` de uno, ese código ya no aparece.

**Checkpoint**: US1 completa. El historial se ve igual en dos navegadores, `localStorage` ya no tiene `radvol3d.history.v1` y `pytest -m "unit or architecture"` y `node --test` están en verde.

---

## Phase 4: User Story 2 - Ver el volumen de lesión de cada estudio (Priority: P1)

**Goal**: cada fila `completed` muestra la suma de los volúmenes de sus lesiones, con el mismo
formato que el visor (FR-006 a FR-008, research.md R5).

**Independent Test**: procesar un estudio con lesiones conocidas. La columna Volumen coincide
con la suma de los volúmenes del visor, al redondeo mostrado (SC-003, quickstart.md §3
paso 4), y la prueba de integración de T025 pasa.

### Tests for User Story 2 ⚠️

- [ ] T021 [P] [US2] Agregar a `tests/unit/web/test_history_view.js` las pruebas de volumen:
  - **`format_volume`**:
    - `format_volume(15.6)` da `"15,6 mm³"`;
    - `format_volume(999)` da `"999 mm³"`;
    - `format_volume(1000)` da `"1 cm³"`;
    - `format_volume(1843.75)` da `"1,8 cm³"`.
  - **`volume_text`**:
    - `{status: "completed", total_lesion_volume_mm3: 0, lesion_count: 0}` da `"Sin lesiones"`;
    - `{status: "completed", total_lesion_volume_mm3: 1843.75, lesion_count: 2}` da `"1,8 cm³"`;
    - `pending`, `processing` y `failed`, con `null`, dan `"—"`.

### Implementation for User Story 2

- [ ] T022 [US2] Agregar a `src/radvol3d/static/js/history_view.js` lo siguiente:
  - **`format_volume(mm3)`**: se mueve tal cual desde `index.html`. Usa `const number_format = new Intl.NumberFormat("es", { maximumFractionDigits: 1 })` y devuelve `mm3 >= 1000 ? number_format.format(mm3 / 1000) + " cm³" : number_format.format(mm3) + " mm³"`.
  - **`volume_text(entry)`**:
    - si no es `completed` o el volumen es `null`, devuelve `"—"`;
    - si es `0`, devuelve `"Sin lesiones"`;
    - si no, devuelve `format_volume(entry.total_lesion_volume_mm3)`.
- [ ] T023 [US2] En `src/radvol3d/static/index.html`:
  - **Visor**: borrar la `function format_volume` local e importar `format_volume` y `volume_text` desde `/static/js/history_view.js`. El visor (`#f-vol`) usa la función importada (SC-003).
  - **Historial**: agregar la columna "Volumen" en `.hhead` y en cada `.hrow`, con `volume_text(entry)`.
  - **Estilos**: ajustar `grid-template-columns` de `.hhead` y `.hrow` en el `<style>` para la columna nueva, con la regla de ancho de teléfono existente.
- [ ] T024 [US2] Revisar que `finding_tag(entry)` de `src/radvol3d/static/index.html` siga funcionando con las entradas de la API: usa `entry.lesion_count`, que ahora es `null` fuera de `completed`. "Sin hallazgo" sale solo con `completed` y `0`.
- [ ] T025 [US2] Agregar a `tests/integration/persistence/test_study_history_integration.py` la prueba de volumen:
  - **Preparación**: dentro de `database.transaction()`:
    - registrar lesiones con `LesionRepository(connection).add_many(code, [Lesion("superior", 12.5, 0.9), Lesion("inferior", 30.25, 0.8)])`;
    - pasar el estudio a `completed` con `StudyRepository(connection).update_status(code, StudyStatus.COMPLETED)`.
  - **Esperado**:
    - `list_history` devuelve `lesion_count == 2` y `total_lesion_volume_mm3 == 42.75`;
    - otro estudio `completed` sin lesiones da `0` y `0.0`.

**Checkpoint**: US2 completa. La columna Volumen coincide con el visor y `node --test` está en verde.

---

## Phase 5: User Story 3 - Identificar al paciente por su DNI y encontrar sus estudios (Priority: P2)

**Goal**:

- cada fila muestra el DNI completo, o "sin DNI" (FR-010);
- el usuario filtra por un DNI de ocho dígitos;
- el DNI va en el cuerpo de `POST /studies/search` y nunca en la URL ni en los registros
  (FR-011, FR-012, research.md R1).

**Independent Test**: crear dos estudios con el mismo DNI y uno con otro, y filtrar por el
primero. Aparecen exactamente los dos (SC-004), el hash sigue en `#/history` y la línea de
acceso de uvicorn no tiene el DNI (quickstart.md §3, pasos 5 y 6).

### Tests for User Story 3 ⚠️

- [ ] T026 [P] [US3] Agregar a `tests/unit/api/test_history_router.py` las pruebas de `POST /studies/search`:
  - **Búsqueda válida**:
    - `{"national_id": "12345678"}` responde 200 y llama a `service.list_history.assert_called_once_with(limit=50, offset=0, national_id="12345678")`;
    - `" 12345678 "` llega limpio;
    - `offset` y `limit` del cuerpo llegan tal cual;
    - un resultado vacío responde 200 con `items: []` y `has_more: false`.
  - **Búsqueda inválida**:
    - `"1234567"`, `"123456789"`, `"1234567a"` y la ausencia del campo responden 422, `response.text` no contiene el valor enviado y el servicio no se llama;
    - `limit=0`, `limit=101` y `offset=-1` responden 422.
  - **DNI en la respuesta**: en `GET /studies`, un item con `national_id="12345678"` sale tal cual y uno sin DNI sale `null`.
  - **Registros** (FR-012): con `caplog.at_level("DEBUG")`, durante un `POST /studies/search` con un DNI válido y otro inválido, `"12345678"` no aparece en `caplog.text`.
- [ ] T027 [P] [US3] Agregar a `tests/unit/web/test_history_view.js` las pruebas del DNI:
  - **`national_id_text`**:
    - `national_id_text({national_id: "12345678"})` da `"12345678"`;
    - `{national_id: null}` da `"sin DNI"`.
  - **`clean_national_id`**:
    - `clean_national_id(" 12a34-5678 ")` da `"12345678"`;
    - `clean_national_id("1234567890")` da `"12345678"` (solo dígitos, como máximo 8).
  - **`is_valid_national_id`**: devuelve `true` solo para exactamente 8 dígitos (`"12345678"`), y `false` para `"1234567"`, `""` y `"1234567a"`.

### Implementation for User Story 3

- [ ] T028 [US3] Agregar a `src/radvol3d/api/routers/history_router.py` la ruta `POST "/search"`:
  - recibe `request: StudySearchRequest`, responde `response_model=StudyHistoryResponse` con 200 y llama a `service.list_history(limit=request.limit, offset=request.offset, national_id=request.national_id)`;
  - no registra nada propio;
  - su docstring explica por qué el DNI va en el cuerpo y no en la URL.
- [ ] T029 [US3] Agregar a `src/radvol3d/static/js/history_view.js` lo siguiente:
  - `national_id_text(entry)` devuelve `entry.national_id` o `"sin DNI"`;
  - `clean_national_id(value)` devuelve `String(value ?? "").replace(/[^0-9]/g, "").slice(0, 8)`;
  - `is_valid_national_id(value)` devuelve `/^[0-9]{8}$/.test(value)`.
- [ ] T030 [US3] En `src/radvol3d/static/index.html`, la columna y el filtro por DNI:
  - **Columna**: agregar "DNI" en `.hhead` y `.hrow`, con `national_id_text(entry)` en `class="mono"` y pasado por `escape_html`. Ajustar `grid-template-columns`.
  - **Filtro**: un formulario `#h-filter` sobre la tabla, con:
    - un campo `#h-dni` (`inputmode="numeric"`, `maxlength="8"`, `autocomplete="off"`, `placeholder="DNI (8 dígitos)"`) que aplica `clean_national_id` al escribir, como `#f-patient-dni`;
    - un botón "Buscar" (`submit`) y otro "Limpiar".
  - **Buscar**:
    - con `!is_valid_national_id(value)`, muestra "El DNI debe tener exactamente 8 dígitos." y no hace ninguna petición;
    - si es válido, guarda el DNI solo en `history_state.national_id` (en memoria) y llama a `load_history(true)`.
  - **Carga**: `load_history` usa `POST /studies/search` con `{national_id, offset, limit}` cuando `history_state.national_id` no es `null`, y `GET /studies` cuando lo es. "Ver más" respeta el modo activo.
  - **Sin resultados**: con el filtro activo y ningún resultado, muestra "No hay estudios para ese DNI".
  - **Limpiar**: borra el campo, pone `history_state.national_id = null` y llama a `load_history(true)`.
  - **Privacidad** (FR-012): el DNI nunca se escribe en `location.hash`, `history.replaceState`, `localStorage`, `sessionStorage` ni `console`.
- [ ] T031 [US3] Agregar a `tests/integration/persistence/test_study_history_integration.py` la prueba del DNI:
  - **DNIs de prueba**: generar dos DNI de 8 dígitos al azar que no existan en `patient` (comprobarlo con una consulta).
  - **Preparación**:
    - crear dos estudios con `PatientDetails(first_name="Prueba", last_name="Historial", national_id=dni_x)` y uno con `dni_y`, con `create_study`;
    - agregar sus `patient_code` a `created_patient_codes`;
    - crear otro estudio sin datos personales.
  - **Esperado**:
    - `store.list_history(limit=50, offset=0, national_id=dni_x)` devuelve exactamente los dos estudios de `dni_x`, del más reciente al más antiguo, con `national_id == dni_x`;
    - el estudio sin datos personales sale con `national_id is None` al buscarlo en `list_history` sin filtro;
    - un DNI sin estudios devuelve `entries == []` y `has_more is False`.

**Checkpoint**: las tres historias están completas y quickstart.md §2 y §3 pasan.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: documentación de la excepción a FR-029, verificación final y medición

- [ ] T032 [P] Documentar la excepción a FR-029 (FR-013):
  - en `specs/004-rest-api-viewer/spec.md`, agregar a FR-029 la nota "Excepción: `GET /studies` y `POST /studies/search` devuelven `national_id` (ver specs/005-persistent-study-history, FR-009 a FR-013)";
  - en `specs/004-rest-api-viewer/contracts/http_api.md`, agregar una sección "Historial" que remite a `specs/005-persistent-study-history/contracts/http_api_history.md`.
- [ ] T033 [P] Agregar la fila `history_router.py` | `GET /studies`, `POST /studies/search` (DNI en el cuerpo) a la tabla de routers de `docs/architecture/fastapi_structure.md`.
- [ ] T034 Correr quickstart.md §1:
  - `ruff check src tests`;
  - `python scripts/check_naming_convention.py`;
  - `pytest -m "unit or architecture"`;
  - `node --test "tests/unit/web/*.js"`;
  - `coverage run -m pytest -m unit && coverage report --include="src/radvol3d/api/*" --fail-under=80`.

  Corregir lo que falle sin tocar `tests/architecture/`.
- [ ] T035 Correr quickstart.md §2 (`pytest -m integration -k history`) contra la base de prueba (`.env.test`).
- [ ] T036 Hacer la validación manual de quickstart.md §3 (pasos 1 a 9) y la medición de §4 (SC-002, 500 estudios), y anotar en este archivo el tiempo medido. Si no se puede medir, dejar `TODO(SC-002)` y no inventar ningún número (Principio V).
- [ ] T037 Buscar en el repositorio los restos de esta funcionalidad:
  - `rg -n "read_history|remember\(|forget\(|HISTORY_KEY" src/radvol3d/static` no devuelve nada, salvo `LEGACY_HISTORY_KEY`;
  - `rg -n "console\.(log|info|debug)" src/radvol3d/static` no imprime ningún DNI.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T002 depende de T001 (hecho).
- **Foundational (Phase 2)**:
  - T004 → T006 → T008 → T010, en cadena: dominio, repositorio, almacén y servicio.
  - T012 depende de T004.
  - Bloquea las tres historias.
- **US1 (Phase 3)**: depende de la Phase 2.
- **US2 (Phase 4)**: depende de la Phase 2.
  - La parte web (T023) toca la misma vista que T018 y T019, así que conviene hacerla después de US1.
  - La parte de datos ya está en la Phase 2.
- **US3 (Phase 5)**:
  - T028 extiende `history_router.py`, que crea T015;
  - T030 extiende la vista de T018.
  - Va después de US1.
- **Polish (Phase 6)**: después de las historias que se vayan a entregar.

### Within Each Phase

- La prueba antes que el código, y debe fallar: T003 → T004, T005 → T006, T007 → T008,
  T009 → T010, T011 → T012, T013 → T015, T014 → T017, T021 → T022, T026 → T028 y T027 → T029.
- Dentro de `src/radvol3d/static/index.html`, las tareas van en orden y nunca en paralelo:
  T018 → T019 → T023 → T024 → T030.
- `src/radvol3d/static/js/history_view.js` crece en orden: T017 → T022 → T029.

### Parallel Opportunities

- **Phase 2**: T003, T005, T007, T009 y T011 son pruebas en archivos distintos. Se escriben a
  la vez.
- **US1**: T013 (router) y T014 (JS) en paralelo. Después, T015 y T016 (API) en paralelo con
  T017 (JS).
- **US2**: T021 en paralelo con T025 (integración).
- **US3**: T026 y T027 en paralelo. T028 (API) en paralelo con T029 (JS).
- **Polish**: T032 y T033 en paralelo.

---

## Parallel Example: Phase 2 (pruebas)

```text
Task: "T003 pruebas de StudyHistoryEntry/StudyHistoryPage en tests/unit/domain/test_entities.py"
Task: "T005 pruebas de StudyRepository.list_history en tests/unit/persistence/repositories/test_study_repository.py"
Task: "T007 pruebas de StudyMetadataStore.list_history en tests/unit/persistence/test_study_metadata_store.py"
Task: "T009 pruebas de StudyService.list_history en tests/unit/services/test_study_service.py"
Task: "T011 pruebas de los esquemas en tests/unit/api/test_history_schema.py"
```

## Parallel Example: User Story 3

```text
Task: "T026 pruebas de POST /studies/search en tests/unit/api/test_history_router.py"
Task: "T027 pruebas de national_id_text/clean_national_id/is_valid_national_id en tests/unit/web/test_history_view.js"
# después:
Task: "T028 ruta POST /search en src/radvol3d/api/routers/history_router.py"
Task: "T029 funciones de DNI en src/radvol3d/static/js/history_view.js"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Phase 1 (T002) y Phase 2 (T003 a T012).
2. Phase 3, US1 (T013 a T020).
3. **Parar y validar**: el historial es el mismo en dos navegadores y no usa
   `localStorage`.
4. Se puede fusionar así: la API ya devuelve el volumen y el DNI, pero la página todavía no
   los muestra.

### Incremental Delivery

1. Base + US1 → historial persistente (MVP).
2. + US2 → columna Volumen, el mismo formato que el visor.
3. + US3 → columna DNI y filtro por DNI.
4. Polish → documentación de la excepción a FR-029 y medición de SC-002.

Commits sugeridos, uno por carpeta (constitución, Flujo de desarrollo):

- `feat(domain): agrega los tipos del historial de estudios`
- `feat(persistence): agrega la consulta del historial con volumen y dni`
- `feat(services): agrega list_history con la regla de estudios terminados`
- `feat(api): agrega get /studies y post /studies/search`
- `feat(static): historial desde la api con volumen y filtro por dni`
- `test(...)`, en el mismo commit que su código o en el siguiente del mismo pull request
- `docs(specs): documenta la excepcion a fr-029 de 004`

---

## Notes

- [P] = archivos distintos y sin dependencias pendientes.
- `index.html` es un solo archivo grande: sus tareas nunca van en paralelo.
- La base de prueba es compartida: las pruebas de integración solo comparan sus propios
  códigos (`SESSION_PREFIX`) y DNI generados al azar.
- No hay migración: si una tarea parece necesitar una columna nueva, es un error de diseño y
  se vuelve a research.md R2.
