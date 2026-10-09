# Implementation Plan: Capa de servicios y tubería de procesamiento

**Branch**: `feat/services-pipeline` | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/002-services-pipeline/spec.md`

## Summary

La funcionalidad conecta las radiografías con el resultado. La capa de lógica recibe un
estudio, valida sus cuatro proyecciones `.npy`, lo registra y lo pasa por una tubería de
cuatro filtros: preprocesamiento, reconstrucción, segmentación y mallas. La tubería registra
cada etapa en la persistencia y guarda el volumen, el resultado y las dos mallas.

Los algoritmos se enchufan con Strategy. Una sola fábrica elige la estrategia según la
configuración y el órgano. Todo se arma una sola vez en el `lifespan`.

El trabajo va en dos bloques:

1. **Con dobles, sin torch.** La tubería, la fábrica, `StudyService`, el borrado y el armado
   del arranque, todo en verde.
2. **Con los modelos reales.** EN-1 y EN-2 migrados de `models/` a `services/` con nombres en
   inglés, y las mallas con scikit-image y trimesh. Una prueba de regresión, con el marcador
   `ml`, demuestra que la salida numérica no cambió.

PyTorch queda como extra opcional. El CI no lo instala, y aun así mide un 80 % de cobertura en
`services/` (research.md R17).

## Technical Context

**Language/Version**: Python 3.11 en el CI, 3.13 en la laptop de desarrollo. `requires-python >= 3.11`.

**Primary Dependencies**:

- Ya presentes: numpy y scipy.
- Nuevas en `requirements.txt`: scikit-image (marching cubes y Otsu) y trimesh (`.glb`).
- Nueva como extra `ml` en `pyproject.toml`: torch, solo CPU.
- Pesos declarados en research.md R3.

**Storage**: Supabase Postgres, con el esquema de 001 sin cambios. Supabase Storage con dos
buckets: el de datos, que ya existe, y el de modelos, nuevo (`MODEL_BUCKET`).

**Testing**: pytest con los marcadores `unit`, `integration`, `concurrency`, `architecture` y
`ml` (nuevo); pytest-cov y coverage.

**Target Platform**: servidor Linux en CPU. El desarrollo es en Windows 11.

**Project Type**: servicio web (FastAPI). Esta funcionalidad no agrega endpoints.

**Performance Goals**: ninguno fijado; no se inventan (Principio V). Referencias medidas para
dimensionar las pruebas:

- EN-1: ≈ 11 s por estudio en CPU (autoprueba original);
- EN-2: ≈ 148 s por estudio en CPU con 4 hilos y TTA (research.md R18);
- mallas: < 0,5 s.

La suite `ml` tarda varios minutos, porque corre EN-2 dos veces.

**Constraints**:

- capas cerradas;
- `api/` sin torch;
- la salida numérica de EN-1 y EN-2 no cambia (tolerancia `1e-5`, máscara exacta);
- servicios gratuitos;
- pesos fuera de git;
- ningún dato personal en errores ni registros.

**Scale/Scope**: un servidor. Dos o más estudios pueden procesarse a la vez y comparten los
modelos. La rejilla es de 128³ (≈ 8 MB por arreglo float32).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Cómo lo cumple el diseño | Estado |
|---|---|---|
| **I. Capas cerradas** | `services/` importa `persistence`, `domain` y `config`. `api/` solo recibe `StudyService` por `Depends()`, leído de `app.state`. El armado vive en `services/service_container.py` y lo llama `main.py`, que no es capa. Los módulos con torch se importan de forma perezosa, así que `api/` no lo arrastra. `test_layer_boundaries.py` no se modifica. | ✅ |
| **II. Strategy, Factory Method y Repository** | Una interfaz por etapa: reconstrucción, segmentación y mallas. Una sola fábrica (`services/strategy_factory.py`) con registros por clave y por órgano. Ningún `if organ ==` en la tubería ni en el servicio. Toda la base y el Storage, incluida la descarga de pesos, pasan por la persistencia. | ✅, con la enmienda PATCH de abajo |
| **III. Nombres en inglés, prosa en español** | Los archivos e identificadores migrados pasan a inglés y snake_case (R14). Comentarios y docstrings en español. Las claves de los `.pth` son formato de archivo, no identificadores, y se mantienen. | ✅ |
| **IV. Prueba unitaria con cada funcionalidad** | Cada pieza nueva tiene su prueba en `tests/unit/`. La tubería y las estrategias se prueban con los dobles de `tests/fixtures/`. Ninguna prueba `unit` carga torch ni pesos: esas pruebas van en `tests/ml/`, con el marcador `ml`. | ✅ |
| **V. Ningún dato inventado, ninguna clave expuesta** | `trained_on` queda vacío, con `TODO(TRAINING_DATE_EN1/EN2)`. Los parámetros del `.pth` de exportación citan su fuente. Las referencias de regresión las genera un script y su SHA-256 queda en un manifiesto. No hay metas de rendimiento. Las credenciales salen de `.env`. | ✅ |
| **Servicios y dependencias** | Solo bibliotecas y servicios gratuitos. El peso de torch, scikit-image y trimesh está declarado (R3) y se repite en el pull request. Los modelos y la base se abren una vez en el `lifespan`. | ✅ |
| **Flujo de desarrollo** | Rama `feat/services-pipeline`. Commits por carpeta: `feat(services)`, `feat(persistence)`, `feat(domain)`, `test(...)`, `docs(...)`, y `docs(specify)` para la enmienda. | ✅ |

**Enmienda PATCH necesaria (1.0.0 → 1.0.1).** El Principio II nombra la ruta
`services/processing_pipeline.py`, y el usuario pidió `services/pipeline/`. El principio no
cambia, solo la ruta citada. Por eso es PATCH, según la sección de Governance. Va en este mismo
pull request:

- un commit `docs(specify): actualiza la ruta de la tuberia en la constitucion`;
- en el mismo cambio, `docs/architecture/design_patterns.md`.

**Re-check después del diseño (Fase 1).** Se revisaron los contratos y el modelo de datos.
Siguen cumpliendo los siete puntos. Hay dos decisiones que tocan a otras capas, y ninguna viola
la constitución:

- La persistencia cambia: `save_result` deja de marcar etapas y se agregan `delete_study`,
  `ProcessingProgressStore`, `ModelWeightsStore` y `ModelSettings`. Las capas no cambian de
  dirección, así que no hace falta `!`. Igual se avisa en el pull request (research.md R7 a
  R10).
- `api/` cambia lo mínimo: los imports de la nueva ruta, `get_study_service` y dos códigos de
  error. No gana dependencias nuevas.

## Project Structure

### Documentation (this feature)

```text
specs/002-services-pipeline/
├── spec.md
├── plan.md                         # este archivo
├── research.md                     # Fase 0: decisiones R1-R22
├── data-model.md                   # Fase 1
├── quickstart.md                   # Fase 1
├── contracts/
│   ├── services_api.md             # lo que services ofrece a api y a main
│   ├── persistence_api_changes.md  # lo que cambia en el contrato de 001
│   └── model_artifacts.md          # bucket de modelos, .pth de exportación, manifiesto
├── checklists/requirements.md
└── tasks.md                        # Fase 2 (/speckit-tasks), no se crea aquí
```

### Source Code (repository root)

```text
src/radvol3d/
├── config.py                           # ACCEPTED_FORMATS = (".npy",)
├── main.py                             # lifespan: build_service_container / close
├── domain/
│   ├── entities.py                     # SegmentationResult.summary
│   └── exceptions.py                   # StageFailedError, StudyInProgressError
├── api/
│   ├── dependencies.py                 # get_study_service(request)
│   ├── error_handlers.py               # + StageFailedError 500, StudyInProgressError 409
│   └── routers/                        # solo imports actualizados
├── persistence/
│   ├── settings.py                     # + ModelSettings, get_model_settings
│   ├── object_storage.py               # + remove_many, bucket opcional en from_settings
│   ├── model_weights_store.py          # nuevo
│   ├── processing_progress_store.py    # nuevo
│   ├── study_metadata_store.py         # + delete_study
│   ├── result_store.py                 # save_result ya no marca etapas
│   └── repositories/study_repository.py   # + lock_status, delete
└── services/
    ├── strategy_factory.py             # StrategyFactory, StrategySet
    ├── study_service.py                # StudyService, StudyRequest
    ├── service_container.py            # build_service_container, ServiceContainer
    ├── pipeline/
    │   ├── processing_pipeline.py      # movido desde services/
    │   ├── pipeline_data.py
    │   ├── filters.py                  # Preprocessing, Reconstruction, Segmentation, Meshing
    │   ├── progress.py                 # PipelineProgress (Protocol)
    │   ├── persistence_progress.py     # adaptador sobre los almacenes de la persistencia
    │   └── projection_loader.py        # movido desde services/preprocessing/
    ├── reconstruction/
    │   ├── reconstruction_strategy.py
    │   ├── en1_geometry.py             # numpy/scipy
    │   ├── en1_network.py              # torch
    │   ├── en1_reconstructor.py        # torch
    │   ├── neural_en1_strategy.py      # envoltorio, torch perezoso
    │   └── backprojection_strategy.py  # esqueleto, sin cambios
    ├── segmentation/
    │   ├── segmentation_strategy.py
    │   ├── lung_region_summary.py      # numpy/scipy
    │   ├── lung_unet_network.py        # torch
    │   ├── lung_segmenter.py           # torch
    │   ├── lung_unet_strategy.py       # envoltorio, torch perezoso
    │   └── liver_unet_strategy.py      # esqueleto, fuera de la fábrica
    └── meshing/
        ├── meshing_strategy.py         # build_meshes -> MeshSet
        └── marching_cubes_strategy.py

scripts/
├── export_en2_weights.py               # Q1 = B
├── generate_regression_reference.py       # FR-034
└── publish_model_artifacts.py          # sube pesos y referencias a MODEL_BUCKET

tests/
├── fixtures/
│   ├── fake_strategies.py              # dobles actualizados a las interfaces nuevas
│   ├── fake_progress.py                # PipelineProgress que guarda eventos
│   └── projection_files.py             # .npy válidos e inválidos, en memoria
├── unit/services/                      # factory, filtros, pipeline, study_service, loader,
│                                       #   mallas, en1_geometry, lung_region_summary,
│                                       #   envoltorios con motor falso, container
├── unit/persistence/                   # delete_study, progress store, weights store,
│                                       #   remove_many, save_result
├── integration/services/               # tubería completa con dobles + Supabase de prueba
├── concurrency/                        # dos estudios a la vez, 20 repeticiones
├── ml/                                 # regresión EN-1/EN-2 + estudio de ejemplo (marcador ml)
│   └── reference/manifest.json
└── architecture/                       # sin cambios

pyproject.toml                          # extra "ml", marcador "ml"
requirements.txt                        # + scikit-image, trimesh
.gitignore                              # + models/, .cache/
.github/workflows/ci.yml                # coverage report --include services --fail-under=80
.env.example, .env.test.example         # + variables de ModelSettings
docs/models/*.md                        # procedencia, métricas de metricas_test.json, TODO de fechas
docs/standards/testing_strategy.md      # + fila ml/
docs/architecture/design_patterns.md    # rutas nuevas, Strategy de mallas
.specify/memory/constitution.md         # enmienda PATCH 1.0.1
```

**Decisión de estructura**: un solo proyecto, con el paquete `src/radvol3d` y sus capas ya
existentes. Dentro de `services/` se usan las cuatro carpetas que pidió el usuario (R1).
`models/` queda como carpeta local, en `.gitignore`. Su contenido migra a `services/` y sus
pesos al bucket de modelos.

## Orden de construcción

1. **Base.** Domain (errores y `summary`), cambios de persistencia (R7 a R10) con sus pruebas
   unitarias, `.gitignore` y marcadores.
2. **Bloque con dobles.**
   1. Interfaces actualizadas y dobles.
   2. Admisión y carga de proyecciones.
   3. Filtros y tubería con `fake_progress`.
   4. Fábrica.
   5. `StudyService`, incluido `delete_study`.
   6. Contenedor, `lifespan` y `dependencies`.
   7. Pruebas de integración y concurrencia.
   8. CI con la cobertura.
3. **Mallas reales** (scikit-image y trimesh). No necesitan torch, así que sus pruebas son
   `unit`.
4. **Modelos reales (último bloque).**
   1. Referencia de regresión con los originales, antes de migrar nada.
   2. Script de exportación de EN-2.
   3. Migración de EN-1 y EN-2 (R14, R15).
   4. Envoltorios.
   5. Pruebas `ml`.
   6. Publicación en el bucket.
   7. Documentación de modelos y enmienda de la constitución.

## Riesgos

| Riesgo | Mitigación |
|---|---|
| La regresión falla en otra máquina por diferencias numéricas de torch o de la CPU | El manifiesto guarda el entorno, y el mensaje de fallo lo muestra. La referencia se generó en CPU. Si hace falta, se regenera en la máquina del CI de modelos y se documenta. |
| El volumen real de EN-1 da una malla de órgano pobre con Otsu | Está aceptado y documentado (FR-026a). El umbral fijo en HU queda como mejora futura. |
| EN-2 tarda minutos por estudio en CPU, y la petición HTTP sincrónica podría vencer | Fuera de alcance: lo decide la capa `api` (tarea en segundo plano). Queda anotado para esa funcionalidad. |
| El cambio de `save_result` rompe las pruebas de 001 | Se actualizan en el mismo pull request, y el contrato de 001 se reescribe (persistence_api_changes.md). |

## Complexity Tracking

No hay violaciones de la constitución que justificar. La ruta de la tubería se resuelve con
una enmienda PATCH (ver Constitution Check), no con una excepción.

La única decisión que se aparta de lo esperado es omitir cuatro módulos con torch del umbral
de cobertura del CI (research.md R17). No viola la constitución, que no fija un umbral, pero
queda registrada:

| Decisión | Por qué hace falta | Alternativa más simple descartada |
|---|---|---|
| Omitir del umbral del CI los cuatro módulos que importan torch | El usuario pidió las dos cosas: CI sin torch y 80 % en `services/` | Instalar torch en el CI (≈ 540 MB), descartado por el usuario. Bajar el umbral, descartado por el usuario. |
