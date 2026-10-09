# Research: Capa de API REST y visor 3D

**Feature**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md) | **Date**: 2026-10-09

Cada decisión cita los requisitos que resuelve. No quedan `NEEDS CLARIFICATION` en el
contexto técnico.

---

## R1. Un router por recurso

**Decision**: cuatro routers nuevos en `api/routers/`, en singular como los que ya existen:

| Archivo | Rutas |
|---|---|
| `study_router.py` (reescrito) | `POST /studies`, `GET /studies/{study_code}/status`, `POST /studies/{study_code}/process`, `DELETE /studies/{study_code}` |
| `projection_router.py` | `POST /studies/{study_code}/projections` |
| `result_router.py` | `GET /studies/{study_code}/result` y las descargas (R6) |
| `viewer_router.py` | `GET /viewer/{study_code}` |

Se borran `reconstruction_router.py`, `segmentation_router.py` y sus esquemas
(`reconstruction_schema.py`, `segmentation_schema.py`). `health_router.py` no cambia.

**Rationale**: FR-001. `process` va en el router de estudios porque actúa sobre el estudio,
no sobre un recurso propio. El visor tiene su router porque no cuelga de `/studies`.

**Alternatives considered**: un router `processing_router.py` solo para `process` (un
archivo de un endpoint, sin ganancia); conservar los routers de reconstrucción y
segmentación (sus rutas no existen en la descripción y lanzan `NotImplementedError`).

---

## R2. El flujo en tres pasos necesita operaciones nuevas en services y persistence

**Decision**: hoy `StudyService.process_study` recibe todo junto y
`StudyMetadataStore.register_study` crea el estudio con sus cuatro proyecciones en una sola
transacción. Se agregan:

- persistencia (`StudyMetadataStore`): `create_study` (paciente, estudio y cuatro etapas
  en `waiting`, sin proyecciones), `add_projections` (bloquea la fila, exige `pending` y cero
  proyecciones, sube y registra las cuatro), `claim_for_processing` (R3) y
  `load_projections` (baja los cuatro arreglos del bucket);
- servicio (`StudyService`): `create_study`, `add_projections`, `start_processing`,
  `run_processing`, `get_completed_result`, `read_result_file`, `read_lesion_mesh` y
  `recover_interrupted_studies`.

`register_study` y `process_study` se conservan, reescritos sobre las piezas nuevas, para
que las pruebas de 001 y 002 sigan valiendo.

**Rationale**: FR-005, FR-009 a FR-015. La presentación no puede guardar proyecciones a la
espera (sería estado en `api/`) ni importar la persistencia (Principio I).

**Alternatives considered**: que `POST /studies/{id}/projections` guarde los archivos en la
memoria del proceso hasta `process` (se pierden al reiniciar y no escalan); que
`POST /studies` reciba también los archivos (contradice la descripción).

---

## R3. Solo un pedido de procesar lanza la tubería

**Decision**: `claim_for_processing(study_code)` abre una transacción, bloquea la fila con
`select ... for update` (`StudyRepository.lock_status`, que ya existe), comprueba que el
estudio esté en `pending` y tenga sus cuatro proyecciones, y lo pasa a `processing`. Si no
cumple, lanza `InvalidStudyStateError` (nuevo, 409). El segundo pedido simultáneo espera el
bloqueo, ve `processing` y recibe 409.

`start_processing` comprueba antes que haya modelo para el órgano
(`StrategyFactory.strategies_for`): si falta, lanza `ModelNotAvailableError` (503) sin tocar
el estado (FR-015).

**Rationale**: FR-014, FR-015. El bloqueo de fila es el mismo mecanismo que ya usa
`delete_study`.

**Alternatives considered**: un `threading.Lock` por código en el proceso (no sirve con más
de un proceso y no protege contra el borrado); un `update ... where status = 'pending'`
sin bloqueo (no permite comprobar las proyecciones en la misma operación).

---

## R4. La tubería corre en una tarea en segundo plano de FastAPI

**Decision**: `POST /process` llama a `service.start_processing(code)` dentro del pedido y,
si no lanza, agrega `service.run_processing(code)` a `BackgroundTasks` y responde
`202 Accepted`. `run_processing` es una función síncrona: Starlette la ejecuta en su
grupo de hilos después de enviar la respuesta, así que el bucle de eventos sigue libre para
las consultas de estado mientras corre EN-2 (≈ 148 s en CPU, research.md R18 de 002).

`run_processing` nunca lanza: baja las proyecciones (`load_projections`), corre la tubería y
cierra el estudio. Si algo falla antes de la tubería (por ejemplo, el bucket), marca el
estudio en `failed` desde la etapa 1 (`fail_from_stage`). Registra el código del estudio y el
tipo del error, nunca su texto (FR-016, FR-029).

**Supuesto de despliegue**: un solo proceso de uvicorn (el valor por omisión). R5 depende de
esto.

**Rationale**: FR-013, FR-016, SC-002, SC-003. Sin dependencias nuevas.

**Alternatives considered**: una cola externa (Celery, RQ) — fuera de alcance por la spec y
agrega un servicio; `asyncio.create_task` con la tubería síncrona dentro (bloquearía el
bucle); un `ThreadPoolExecutor` propio en el contenedor (más código para lo mismo que ya da
Starlette).

---

## R5. Los estudios colgados pasan a `failed` al arrancar

**Decision**: `ProcessingProgressStore.fail_interrupted_studies()` busca los estudios en
`processing` y, por cada uno, en una transacción: la etapa en `running` pasa a `failed`
(si no hay ninguna, la primera en `waiting`), las siguientes a `skipped` y el estudio a
`failed`. Devuelve los códigos. `StudyService.recover_interrupted_studies()` la llama y
`build_service_container` la invoca una vez, al arrancar. El arranque registra cuántos
estudios se recuperaron (solo códigos).

**Rationale**: edge case "el servidor se reinicia", FR-017. Con un solo proceso (R4),
ningún estudio en `processing` puede tener una tarea viva al arrancar.

**Alternatives considered**: una marca de tiempo con vencimiento (necesita fijar un tiempo
máximo que no está en el repositorio, Principio V); no hacer nada (el estudio no se podría
borrar nunca, porque `delete_study` rechaza `processing`).

---

## R6. Las descargas pasan por el propio servicio

**Decision**: el resultado devuelve rutas relativas del servicio, no del bucket:

| Archivo | Ruta | Tipo de contenido |
|---|---|---|
| malla del órgano | `GET /studies/{code}/result/organ.glb` | `model/gltf-binary` |
| malla del tumor completo | `GET /studies/{code}/result/tumor.glb` | `model/gltf-binary` |
| volumen | `GET /studies/{code}/result/volume.npy` | `application/octet-stream` |
| malla de la lesión `n` | `GET /studies/{code}/result/lesions/{n}.glb` | `model/gltf-binary` |

`n` es la posición de la lesión en la lista del resultado, desde 1. No es `region_id` ni
`lesion_id` (FR-021). Cada ruta llama a `service.read_result_file` o
`service.read_lesion_mesh`, que exigen el estudio en `completed` y piden los bytes a
`ResultStore`. Los tipos de contenido se declaran en `api/` (no se importa la constante de
la persistencia). Las respuestas llevan `Content-Disposition: attachment` salvo las `.glb`,
que el visor carga.

**Rationale**: FR-018, FR-020. El bucket sigue privado, la clave de servicio nunca sale del
servidor y ninguna dirección vence mientras el visor carga.

**Alternatives considered**: URLs firmadas de Supabase Storage (vencen, exponen el host del
bucket y obligan a `services/` a conocer un concepto de Storage); hacer público el bucket
(expone todos los estudios).

---

## R7. Subida de las cuatro proyecciones

**Decision**: `multipart/form-data` con cuatro campos de archivo con nombre fijo:
`angle_000`, `angle_045`, `angle_090` y `angle_135`. El ángulo sale del nombre del campo,
nunca del nombre del archivo. Cada campo es obligatorio. Por cada archivo, el router lee a
lo sumo `config.MAX_PROJECTION_BYTES + 1` bytes; si llegan más, responde 413 sin leer el
resto. `MAX_PROJECTION_BYTES = 1_048_576` (1 MiB): un `.npy` de 128 × 128 pesa 65 664 bytes
en float32 y 131 200 en float64, así que el límite deja margen sin aceptar archivos
absurdos. La validación del contenido es la de `ProjectionLoader.parse`, sin cambios.

**Rationale**: FR-009, FR-010, FR-012. `python-multipart` ya está en `requirements.txt`.

**Alternatives considered**: un solo campo con cuatro archivos y el ángulo en el nombre del
archivo (frágil, contradice el edge case); cuatro pedidos, uno por ángulo (deja estudios con
proyecciones a medias).

---

## R8. Errores: un solo lugar, sin datos personales

**Decision**: `api/error_handlers.py` sigue siendo el único traductor y se amplía:

| Error del dominio | HTTP |
|---|---|
| `StudyNotFoundError`, `StorageObjectNotFoundError` | 404 |
| `InvalidStudyIdError` | 400 |
| `InvalidProjectionError`, `InvalidPatientDataError`, `UnknownOrganError` | 422 |
| `DuplicateStudyError`, `StudyInProgressError`, `InvalidStudyStateError` | 409 |
| `ModelNotAvailableError`, `DatabaseUnavailableError` | 503 |
| `StorageError`, `StageFailedError`, `PersistenceError`, `InvalidLesionError`, `PatientCodeExhaustedError` | 500 |
| cualquier otra excepción | 500, mensaje genérico, sin traza |
| archivo de proyección mayor que el límite | 413 (lo decide el router, no es error del dominio) |

Dos cambios más:

- El cuerpo de error pasa de `{"detalle": ...}` a `{"detail": ...}`: los campos van en
  inglés (Principio III), y así coincide con los errores propios de FastAPI.
- Se reemplaza el manejador de `RequestValidationError`. El de FastAPI devuelve el campo
  `input` con el valor recibido, y con un DNI mal escrito eso lo devolvería en la respuesta.
  El nuevo devuelve solo `loc`, `msg` y `type` (FR-029).

**Rationale**: FR-028, FR-029, SC-005.

**Alternatives considered**: un `try/except` por router (repite la tabla en cada archivo);
dejar el 422 de FastAPI (filtra datos del paciente).

---

## R9. Una malla por lesión: cómo se separa cada región

**Decision**: la etapa de mallas recibe, además del volumen y la máscara, las regiones del
resumen (`summary["regions"]` con `has_lesion` verdadero). Una función pura nueva,
`split_lesion_masks(mask, regions)` en `services/meshing/lesion_regions.py`:

1. etiqueta la máscara con `scipy.ndimage.label` y la conectividad por omisión, la misma que
   usa `summarize_regions`;
2. para cada región, busca la componente con el mismo número de vóxeles (`voxels`) y el
   mismo centroide redondeado (`centroid_voxel`);
3. devuelve una máscara booleana por región, en el orden del resumen.

Si una región no encuentra su componente, lanza `ValueError` y la etapa 4 falla: es un error
de programa, y mezclar lesiones sería peor que fallar.

En EN-2, la máscara ya está limpia (`clean_mask` con `min_voxels`) y el resumen se calcula
sobre esa misma máscara (`lung_segmenter.py`, líneas 144-145). Por eso cada componente
tiene exactamente una región y la correspondencia es exacta.

`MeshSet` gana `lesions: tuple[bytes, ...]`, una `.glb` por región y en el mismo orden.
`MarchingCubesStrategy` genera cada una con `_surface(region, shape, TUMOR_STEP)`, con las
mismas coordenadas que el órgano y el tumor. Una región sin superficie extraíble da un
`.glb` válido sin geometría.

**Rationale**: FR-021a, Clarifications Q1 y Q2. Usa datos que el resumen ya trae, sin cambiar
la salida de EN-2 (FR-023a de 002).

**Alternatives considered**: volver a ordenar las componentes por tamaño como
`summarize_regions` (depende de que el orden y los empates coincidan); pedir a la
segmentación un mapa de etiquetas (obliga a cambiar la salida de EN-2 o a recalcularla
igual en la estrategia); separar el `tumor.glb` en el navegador (no enlaza con las filas).

---

## R10. Ruta de cada malla de lesión y enlace con su fila

**Decision**: `storage_layout.lesion_mesh_path(study_code, lesion_number)` devuelve
`<study_code>/meshes/lesion_<NNN>.glb`, con `lesion_number` desde 1 y tres dígitos, como
`angle_000.npy`. El número es la posición de la región en el resumen. La fila de `lesion`
guarda esa ruta en `mesh_path`, y ese es el único enlace: `region_id` no llega a la base.

La documentación de `storage_layout.py`, del diccionario de datos y del contrato de 001
deja de decir "reservada `lesion_<region_id>.glb`" y pasa a describir esta ruta.

**Rationale**: FR-021c. El nombre del archivo no necesita `region_id` porque el enlace es
`mesh_path` (Clarifications Q2).

**Alternatives considered**: `lesion_<region_id>.glb` (en EN-2 el número coincide, pero el
nombre volvería a atar la base a un campo que la spec deja fuera); `lesion_<lesion_id>.glb`
(el id se conoce recién después del insert, y los archivos se suben antes).

---

## R11. Columna `organ` en `lesion`

**Decision**: migración nueva `docs/database/schema/002_add_lesion_organ.sql`:

1. `alter table lesion add column organ varchar(32)`;
2. llenar las filas existentes con el `organ.name` de su estudio;
3. `set not null`;
4. `constraint lesion_organ_allowed check (organ in ('lung', 'liver'))`, igual que
   `organ_name_allowed`.

`LesionRepository.add_many` no recibe el órgano: lo toma del estudio dentro del mismo
`insert ... select`, así no puede quedar desalineado. `list_by_study` lo devuelve en
`Lesion.organ` (campo nuevo, `OrganName | None`). `001_create_tables.sql` no se toca: es el
punto de partida, y la 002 se aplica encima, como se aplicó la 001 (en el editor SQL de
Supabase, en la base real y en la de prueba).

**Rationale**: FR-021b, Clarifications Q3.

**Alternatives considered**: clave foránea a `organ` (la descripción pide texto); recibir el
órgano desde el servicio (dos fuentes del mismo dato); editar la 001 (una base ya creada no
la volvería a ejecutar sin borrar todo).

---

## R12. El borrado también quita las mallas por lesión

**Decision**: `ObjectStorage` gana `list_names(folder)`, sobre el `list` del bucket de
Supabase. `StudyMetadataStore.delete_study` borra las diez rutas fijas de hoy más los
`lesion_*.glb` que encuentre en `<study_code>/meshes/`. Se lista la carpeta, y no se leen
las filas de `lesion`, para limpiar también los archivos de un guardado que falló antes de
insertar las filas.

**Rationale**: FR-021d, SC-001.

**Alternatives considered**: leer `mesh_path` de las filas (deja huérfanos tras un fallo);
borrar con un número máximo de lesiones fijo (inventa un límite).

---

## R13. El visor: página estática, Three.js por CDN

**Decision**:

- `GET /viewer/{study_code}` valida el código y devuelve `web/viewer.html` con
  `FileResponse`: 200 si el estudio existe, 404 con la misma página si no. La página lee el
  código de su propia URL; no se genera HTML en el servidor.
- `viewer.html` usa rutas absolutas (`/css/main.css`, `/js/viewer_3d.js`), porque la página
  vive en `/viewer/<code>` y una ruta relativa apuntaría a `/viewer/js/...`.
- Three.js, `GLTFLoader` y `OrbitControls` se cargan con un `importmap` desde
  `cdn.jsdelivr.net/npm/three@<versión>/`. Se fija una versión exacta publicada en npm, que
  se verifica al implementar; no se usa `latest`. Es gratis y no suma peso al repositorio.
  Copiarlo al repositorio haría fallar `check_naming_convention.py`, que revisa todo `.js`.
- La lógica que no dibuja va en `web/js/viewer_state.js`, sin Three.js ni DOM: la paleta de
  colores, las filas de la lista y el mensaje de cada estado. `viewer_3d.js` arma la escena
  con esas piezas.
- Materiales: órgano `MeshStandardMaterial` con `transparent: true`, opacidad 0,3 y
  `depthWrite: false`, para que las lesiones se vean a través; cada lesión opaca, con un
  color de la paleta. La paleta es la de Okabe-Ito sin el negro: siete colores
  distinguibles también con daltonismo. El órgano va en gris claro. Desde la octava lesión
  la paleta se repite (edge case).
- Resaltar: al elegir una fila, su malla gana un color emisivo y las demás bajan la
  opacidad; otro clic lo deshace.
- Cámara: la vista inicial encuadra la caja que contiene al órgano. Un botón vuelve a ella.
- Estados: si el estudio está `pending` o `processing`, la página muestra el estado y lo
  vuelve a consultar cada 5 s; en `completed` carga las mallas; en `failed` muestra la etapa
  que falló. Sin WebGL, muestra un aviso y los enlaces de descarga.
- Nombres: snake_case en todas las declaraciones (Principio III). Los métodos de Three.js
  (`setSize`, `traverse`...) son de una biblioteca externa y no se declaran aquí;
  `check_naming_convention.py` solo revisa declaraciones.

**Rationale**: FR-022 a FR-027, SC-004.

**Alternatives considered**: copiar Three.js al repositorio (rompe la verificación de
nombres y suma ~1 MB); `<model-viewer>` (no permite materiales por malla ni resaltar);
generar el HTML con plantillas en el servidor (agrega Jinja2 sin necesidad).

---

## R14. Pruebas de la lógica del visor con `node --test`

**Decision**: `tests/unit/web/test_viewer_state.js` prueba `viewer_state.js` con el
ejecutor de pruebas que trae Node (`node:test` y `node:assert`), sin npm ni dependencias. El
CI agrega `actions/setup-node@v4` con Node 22, que detecta solo los módulos ES, y el paso
`node --test tests/unit/web/`. Lo que necesita un navegador (que la escena se dibuje) se
verifica a mano con quickstart.md.

**Rationale**: Principio IV (toda funcionalidad con su prueba unitaria en `tests/unit/`).
Node ya viene en los runners de GitHub; no suma dependencias al proyecto.

**Alternatives considered**: Playwright (descarga navegadores, cientos de MB); no probar el
JavaScript (viola el Principio IV); Jest o Vitest (traen `node_modules`).

---

## R15. Pruebas por nivel

**Decision**:

- `tests/unit/api/`: cada router con `create_app(container_builder=FakeServiceContainer)` y
  `TestClient`, con el servicio simulado (`create_autospec`). Camino feliz, cada error de
  R8, forma de las respuestas, 413, el 422 sin `input`, y que `process` agregue la tarea en
  segundo plano una sola vez.
- `tests/unit/services/` y `tests/unit/persistence/`: las operaciones nuevas de R2, R3, R5,
  R9, R10, R11 y R12 con los dobles que ya existen (`FakeDatabase`, `InMemoryBucket`).
- `tests/integration/`: la migración 002 aplicada, `organ` y `mesh_path` por fila, el
  bloqueo de `claim_for_processing` y el borrado sin huérfanos, contra el Supabase de prueba.
- `tests/e2e/test_http_flow.py` (marcador `e2e`): crear, subir, procesar, consultar, pedir
  el resultado, bajar las mallas y borrar con `TestClient` sobre la aplicación armada con
  los dobles de estrategia y el Supabase de prueba (FR-031). `TestClient` corre la tarea en
  segundo plano al terminar la respuesta, así que la prueba es determinista.
- `tests/concurrency/test_background_processing.py`: uvicorn real en un hilo, con una
  estrategia doble que espera un evento. Mientras espera, las consultas de estado de otro
  estudio responden en menos de 1 s (FR-032, SC-003).
- CI: un paso nuevo mide la cobertura de `api/` con `--fail-under=80` (SC-007).

**Rationale**: FR-030 a FR-033, Principio IV.

---

## R16. Lo que ve el cliente de un estudio

**Decision**: las respuestas de estudio traen `study_code`, `organ`, `status`,
`created_at`, `total_time_sec` y `patient_code`. Nunca nombre, apellido ni DNI. Los datos
personales solo entran por `POST /studies` y no vuelven a salir por la API. Los esquemas
de Pydantic no tienen esos campos, así que no pueden filtrarse por error.

**Rationale**: FR-029.

---

## Peso de dependencias

No se agrega ninguna dependencia de Python. Three.js se carga desde una red de distribución
gratuita y no entra al repositorio. Node se usa solo en el CI para `node --test`, sin
paquetes.
