<!--
Sync Impact Report
==================
Cambio de versión: plantilla sin versión → 1.0.0 (primera ratificación)

Principios definidos:
- [PRINCIPLE_1_NAME] → I. Capas cerradas (NO NEGOCIABLE)
- [PRINCIPLE_2_NAME] → II. Strategy, Factory Method y Repository
- [PRINCIPLE_3_NAME] → III. Nombres en inglés, prosa en español
- [PRINCIPLE_4_NAME] → IV. Toda funcionalidad llega con su prueba unitaria (NO NEGOCIABLE)
- [PRINCIPLE_5_NAME] → V. Ningún dato inventado, ninguna clave expuesta

Secciones agregadas:
- [SECTION_2_NAME] → Servicios y dependencias
- [SECTION_3_NAME] → Flujo de desarrollo
- Governance (completada)

Secciones eliminadas: ninguna.

Plantillas dependientes: no se modifican en este comando; las plantillas de Spec Kit leen
esta constitución al ejecutarse.

Diferencias entre esta constitución y docs/ (no se modificó docs/):
- docs/architecture/layered_architecture.md prohíbe en la presentación solo `persistence` y
  `psycopg`. Esta constitución agrega `supabase` y `torch`. Hay que alinear el documento y
  comprobar que tests/architecture/test_layer_boundaries.py cubra los cuatro.
- docs/architecture/design_patterns.md lista estrategias de reconstrucción y segmentación,
  pero no de mallas. Esta constitución exige Strategy también para mallas.

Pendientes:
- TODO(HEAVY_DEPENDENCY_THRESHOLD): el repositorio no fija a partir de cuántos MB una
  dependencia cuenta como "pesada". Queda como pregunta abierta. No se inventó un número.
-->

# RadVol3D Constitution

## Core Principles

### I. Capas cerradas (NO NEGOCIABLE)

- Cada capa llama solo a la capa inmediatamente inferior: presentación (`api/`, `web/`) →
  lógica (`services/`) → persistencia (`persistence/`) → datos (Supabase).
- `domain/` no es una capa: es el piso compartido. Contiene entidades, enumerados y errores,
  sin lógica ni entrada/salida, y no importa nada del proyecto. Todas las capas pueden
  importarlo.
- `persistence/` MUST NOT importar `fastapi` ni `starlette`.
- `api/` MUST NOT importar `persistence`, `psycopg`, `supabase` ni `torch`.
- La presentación recibe los servicios mediante `Depends()`. No los construye.
- `tests/architecture/test_layer_boundaries.py` verifica estos límites en cada push. Si
  falla, se corrige el import. La prueba nunca se modifica para que pase.

**Razón:** si la persistencia supiera de la web, cambiar de servidor obligaría a reescribir
el acceso a datos. Si la presentación supiera de la base, un cambio de columna llegaría
hasta el HTML. Los tipos compartidos en `domain/` hacen que los errores de forma aparezcan
al escribir el código y no durante la demostración.

### II. Strategy, Factory Method y Repository

- La reconstrucción, la segmentación y la generación de mallas MUST implementarse con
  Strategy: una interfaz por etapa y una clase concreta por algoritmo, todas con la misma
  firma.
- La estrategia que corresponde a cada órgano se elige en un solo lugar, la fábrica
  (`services/strategy_factory.py`).
- La tubería (`services/processing_pipeline.py`) y los servicios MUST NOT contener
  condicionales por órgano (`if organ == ...`). Para agregar un órgano o un algoritmo se
  agrega una clase que implementa la interfaz. La tubería no se toca.
- El acceso a datos pasa por repositorios en `persistence/repositories/`. Ninguna otra
  parte del sistema escribe SQL ni llama a Storage directamente.

**Razón:** una sola tubería sirve a todos los órganos. La tabla `model` ya registra qué
estrategia corrió en cada estudio. Strategy además permite probar la tubería sin GPU ni
pesos (ver Principio IV).

### III. Nombres en inglés, prosa en español

- Van en inglés: módulos, carpetas, clases, funciones, variables, tablas y columnas.
- Van en español: comentarios, docstrings y mensajes al usuario.
- Python y JavaScript usan una sola convención, snake_case. Las clases van en PascalCase
  (PEP 8) y las constantes en MAYÚSCULAS. `camelCase` está prohibido en funciones y
  variables, también en JavaScript.
- `ruff check src tests` (reglas `N`) y `python scripts/check_naming_convention.py` lo
  verifican en cada push. Un cambio que no pase ambos no se fusiona.

**Razón:** una sola convención en todo el proyecto. snake_case en JavaScript es una
desviación deliberada de la costumbre del lenguaje, y queda escrita para que se lea como
decisión y no como descuido.

### IV. Toda funcionalidad llega con su prueba unitaria (NO NEGOCIABLE)

- Cada funcionalidad nueva MUST llegar en el mismo pull request con su prueba unitaria en
  `tests/unit/` (marca `unit`). Sin excepción. Un pull request sin ella no se fusiona.
- Las estrategias y la tubería se prueban con los dobles de `tests/fixtures/`. Una prueba
  unitaria MUST NOT cargar modelos reales, pesos, GPU ni PyTorch.
- Las pruebas unitarias no dependen de nada externo. Lo que necesita Supabase va en
  `integration/`. Lo que necesita el servicio levantado va en `e2e/` o en `concurrency/`.
- La cobertura se mide en el pipeline de integración continua.

**Razón:** que una prueba unitaria corra en milisegundos es lo que hace que se puedan exigir
siempre. Cargar modelos reales las volvería lentas y dependientes del hardware.

### V. Ningún dato inventado, ninguna clave expuesta

- Ninguna clave, token ni contraseña aparece en el código ni en los commits. Toda credencial
  se lee desde `.env`, que nunca se versiona.
- No se inventan datos: ni métricas, ni rutas, ni fechas, ni resultados, ni nombres de
  archivo. Si un dato no está en el repositorio, se registra como pregunta abierta
  (`TODO(...)` o una sección de preguntas abiertas en la especificación). Nunca se rellena
  con un valor plausible.

**Razón:** RadVol3D procesa estudios médicos y reporta resultados de modelos. Una métrica o
una ruta inventada no se distingue de una real y contamina las conclusiones. Una clave
publicada en un commit queda expuesta aunque después se borre.

## Servicios y dependencias

- Solo se usan servicios gratuitos. Un servicio de pago MUST NOT entrar al proyecto.
- Antes de agregar una dependencia pesada, el pull request MUST declarar cuánto pesa y por
  qué hace falta. Si hay un `plan.md`, la declaración va también ahí.
- Los modelos y la conexión a PostgreSQL se abren una sola vez, en el `lifespan` de
  FastAPI. No se abren en cada petición.
- TODO(HEAVY_DEPENDENCY_THRESHOLD): el umbral en MB a partir del cual una dependencia cuenta
  como "pesada" no está definido en el repositorio. Mientras no se defina, se declara el
  peso de toda dependencia que traiga binarios, modelos o frameworks de aprendizaje
  automático.

## Flujo de desarrollo

- **Ramas:** Conventional Branch, `<tipo>/<descripcion>`, en minúsculas, en inglés y con
  guiones (`feat/lesion-repository`, `fix/study-status-mapping`).
- **Commits:** Conventional Commits 1.0.0. El tipo y el ámbito van en inglés y la
  descripción en español, después de los dos puntos. El ámbito es la carpeta tocada
  (`feat(persistence): agrega el repositorio de lesiones`). Los tipos permitidos son `feat`,
  `fix`, `docs`, `test`, `refactor` y `chore`. `!` marca un cambio que rompe compatibilidad
  con otra capa, y hay que avisarlo en el mismo pull request.
- **Antes de cada commit:** `pytest -m "unit or architecture"`, `ruff check src tests` y
  `python scripts/check_naming_convention.py`.
- **Fusión:** solo por pull request, nunca directo a `main`. El pull request MUST pasar la
  integración continua. Si SonarCloud marca el Quality Gate, se revisa la condición que
  falló (**Details**) antes de fusionar.

## Governance

- Esta constitución prevalece sobre cualquier otra práctica del proyecto. `docs/standards/`
  y `docs/architecture/` la detallan y no pueden contradecirla. Si hay contradicción, se
  corrige el documento.
- **Enmiendas:** se proponen por pull request con commit `docs(specify): ...`. El pull
  request explica el motivo y actualiza en el mismo cambio los documentos de `docs/` y las
  pruebas de arquitectura afectados.
- **Versionado (SemVer):** MAJOR cuando se elimina o redefine un principio de forma
  incompatible. MINOR cuando se agrega un principio o una sección, o cuando se amplía una
  guía de forma material. PATCH cuando se aclara o corrige la redacción sin cambiar el
  significado.
- **Cumplimiento:** cada revisión de pull request verifica los cinco principios. El
  "Constitution Check" de `/speckit-plan` MUST pasar antes de diseñar y de nuevo después del
  diseño. Toda excepción se justifica por escrito en la tabla de complejidad del plan. Los
  Principios I y IV no admiten excepciones.
- Para la guía de desarrollo del día a día se consultan `docs/standards/` y
  `docs/architecture/`.

**Version**: 1.0.0 | **Ratified**: 2026-10-08 | **Last Amended**: 2026-10-08
