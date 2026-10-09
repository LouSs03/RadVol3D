# Implementation Plan: Migración de la capa de persistencia al esquema en inglés

**Branch**: `001-persistence-schema-migration` | **Date**: 2026-10-09 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-persistence-schema-migration/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

La funcionalidad completa los trece componentes de `src/radvol3d/persistence/` sobre el esquema en
inglés (`docs/database/schema/001_create_tables.sql`):

- la configuración, la conexión, las rutas del bucket y el almacenamiento de objetos;
- siete repositorios, uno por tabla;
- dos almacenes que coordinan repositorios y bucket en una sola unidad.

Enfoque técnico, según lo pedido:

- **Base de datos:** psycopg 3 contra el pooler de sesión de Supabase, con un grupo de
  conexiones abierto una sola vez.
- **Repositorios:** patrón Repository. Cada uno recibe la conexión de una unidad de trabajo, y
  la unidad de trabajo es lo que hace atómicas las operaciones de varias tablas.
- **Tipos:** entran y salen dataclasses de `domain/entities.py`. Las filas y los errores de
  psycopg nunca salen de la capa.
- **Pruebas:** una prueba unitaria por repositorio, y por cada uno de los demás componentes. Usan
  dobles de `tests/fixtures/`, sin base, sin bucket y sin red. Las pruebas de integración contra
  un Supabase de prueba cubren lo que los dobles no pueden probar: el SQL real y los nombres de
  las restricciones.

## Technical Context

**Language/Version**: Python ≥ 3.11 (`pyproject.toml`). El entorno local usa 3.13.13.

**Primary Dependencies**:

| Dependencia | Estado | Uso |
|---|---|---|
| psycopg 3 (`psycopg[binary]>=3.1`) | ya declarada; instalada la 3.3.6 | acceso a PostgreSQL |
| psycopg-pool | **nueva**, vía el extra `psycopg[binary,pool]`; wheel 3.3.3 de 40 304 bytes, Python puro | grupo de conexiones |
| supabase (`>=2.7`) | ya declarada; instalados supabase y storage3 2.32.0 | Storage |
| pydantic-settings, python-dotenv | ya declaradas | configuración |
| numpy | ya declarada | serialización `.npy` |

**Storage**: PostgreSQL de Supabase a través del pooler de sesión (`DATABASE_URL`) y el bucket de
Supabase Storage (`STORAGE_BUCKET`).

**Testing**: pytest con las marcas `unit`, `integration` y `architecture` de `pyproject.toml`.
Los dobles van en `tests/fixtures/`.

**Target Platform**: el proceso del servicio FastAPI. La plataforma de despliegue no está
definida en el repositorio, y esta funcionalidad no depende de ella.

**Project Type**: servicio web, proyecto único con `src/`.

**Performance Goals**: ninguna. La especificación no fija metas y la constitución prohíbe
inventarlas.

**Constraints**:

- Solo servicios gratuitos: plan gratuito de Supabase.
- `persistence/` no importa `fastapi` ni `starlette`, y solo importa `domain` y `config` del
  paquete.
- Ninguna credencial ni dato personal llega a mensajes o registros.
- No se conoce el límite de clientes del pooler en el plan gratuito. El tamaño máximo del
  grupo es una decisión de diseño (ver research.md, R1) que las pruebas de concurrencia deben
  confirmar.

**Scale/Scope**: 13 componentes, 7 tablas, 7 tipos de archivo por estudio en el bucket.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principio | Verificación | Antes | Después |
|---|---|---|---|
| I. Capas cerradas | `persistence/` importa solo `domain`, `config`, psycopg, psycopg_pool, supabase/storage3, pydantic-settings y numpy. Ninguno está prohibido en `FORBIDDEN_EXTERNAL_LIBRARIES["persistence"]`. Los componentes se conectan con los servicios fuera de esta funcionalidad (R13) para no forzar a `api/` a importar `persistence`. | ✅ | ✅ |
| II. Patrones | Un repositorio por tabla en `persistence/repositories/`. Ninguna otra parte escribe SQL ni llama a Storage. No hay condicionales por órgano: el órgano es un dato. | ✅ | ✅ |
| III. Nombres e idioma | Nombres en inglés y snake_case. Docstrings y mensajes de error en español. Se verifica con `ruff` (reglas N) y `scripts/check_naming_convention.py`. | ✅ | ✅ |
| IV. Prueba unitaria por funcionalidad | Cada componente tiene su archivo en `tests/unit/persistence/`, con dobles de `tests/fixtures/` (`fake_database.py` y `fake_object_storage.py`) y sin red. | ✅ | ✅ |
| V. Sin datos inventados ni claves expuestas | Las credenciales se guardan como `SecretStr` y se leen de `.env`. Los errores no copian el texto de psycopg (trae valores en `DETAIL`). El paciente se muestra sin sus datos personales. El peso de psycopg-pool se midió. Los dos valores que no salen de una medición están marcados como decisiones (R1). | ✅ | ✅ |
| Servicios y dependencias | Supabase en el plan gratuito. psycopg-pool tiene su peso declarado: 40 304 bytes. | ✅ | ✅ |
| Flujo de desarrollo | La rama actual es `chore/spec-kit`. La implementación MUST ir en `feat/persistence-schema-migration`. | ⚠️ pendiente, no bloquea | ⚠️ |

**Resultado:** pasa. No hay violaciones que justificar.

## Project Structure

### Documentation (this feature)

```text
specs/001-persistence-schema-migration/
├── plan.md              # este archivo
├── research.md          # Fase 0: decisiones técnicas
├── data-model.md        # Fase 1: entidades, tablas, validaciones y estados
├── quickstart.md        # Fase 1: cómo validar la funcionalidad
├── contracts/
│   └── persistence_api.md   # Fase 1: lo que la capa ofrece a services/
├── checklists/
│   └── requirements.md
└── tasks.md             # Fase 2 (/speckit-tasks), no lo crea este comando
```

### Source Code (repository root)

```text
src/radvol3d/
├── domain/
│   ├── entities.py          # MOD: Patient, PatientDetails, Model, StoredResult;
│   │                        #      campos nuevos en Study y ProcessingStage
│   └── exceptions.py        # MOD: errores nuevos (ver data-model.md)
└── persistence/
    ├── settings.py          # configuración desde .env
    ├── connection.py        # grupo de conexiones y unidad de trabajo
    ├── database_errors.py   # NUEVO: traduce errores de psycopg a errores del dominio
    ├── storage_layout.py    # rutas del bucket
    ├── object_storage.py    # subir, bajar y comprobar en el bucket; .npy sin pickle
    ├── study_metadata_store.py
    ├── result_store.py
    └── repositories/
        ├── patient_repository.py          # NUEVO
        ├── organ_repository.py
        ├── model_repository.py
        ├── study_repository.py
        ├── projection_repository.py
        ├── processing_stage_repository.py
        └── lesion_repository.py

tests/
├── fixtures/
│   ├── fake_database.py        # NUEVO: conexión y cursor guionados, errores de psycopg con restricción
│   └── fake_object_storage.py  # NUEVO: bucket en memoria
├── unit/persistence/
│   ├── test_settings.py
│   ├── test_connection.py
│   ├── test_database_errors.py
│   ├── test_storage_layout.py
│   ├── test_object_storage.py
│   ├── test_study_metadata_store.py
│   ├── test_result_store.py
│   └── repositories/
│       └── test_<tabla>_repository.py   # siete archivos, uno por repositorio
└── integration/persistence/
    ├── conftest.py              # lee .env.test; si no existe, omite las pruebas
    └── test_<componente>_integration.py

requirements.txt                 # MOD: psycopg[binary] → psycopg[binary,pool]
.gitignore                       # MOD: agrega .env.test
.env.test.example                # NUEVO: mismas cuatro variables, para el Supabase de prueba
```

**Structure Decision**: es un proyecto único con `src/` y las carpetas de capas que ya existen.
Solo se agregan tres archivos de código: `database_errors.py`, `patient_repository.py` y los dos
dobles de `tests/fixtures/`. El resto completa archivos que hoy son solo un `TODO`.

## Complexity Tracking

No hay violaciones de la constitución que justificar.

## Fuera de alcance (registrado para no perderlo)

- **Conexión con los servicios y la aplicación.** Abrir la base en `lifespan` y construir
  `StudyService` con estos componentes requiere una función de armado en `services/`, porque
  `api/` no puede importar `persistence`. Esa función se hace en la funcionalidad de servicios.
  Esta funcionalidad deja listo `Database.open()` / `close()` (R13).
- **Borrado de estudios.** `StudyService.delete_study` ya existe como `TODO`, pero la
  especificación deja fuera el borrado de estudios. La persistencia no ofrece una operación de
  borrado.
