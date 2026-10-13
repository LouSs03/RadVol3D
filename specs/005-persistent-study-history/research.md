# Research: Historial de estudios persistente con volumen de lesión y DNI

Decisiones de la Fase 0. Cada una cita el código que la motiva. No quedó ningún
"NEEDS CLARIFICATION" en el contexto técnico: las dos preguntas de la spec se resolvieron
en la sesión de aclaraciones del 2026-10-12.

## R1. El DNI del filtro viaja en el cuerpo, no en la URL

**Decision**: dos rutas.

- `GET /studies?offset=&limit=` lista todos los estudios. La URL nunca lleva DNI.
- `POST /studies/search` filtra por DNI, que va en el cuerpo JSON
  (`{"national_id": "12345678", ...}`).

**Rationale**:

- uvicorn registra cada petición con su ruta y su query string (el registro de acceso).
  Un `GET /studies?national_id=12345678` dejaría el DNI en ese registro, y FR-012 prohíbe
  que el DNI aparezca en los registros del sistema.
- El cuerpo de una petición no se registra: ni uvicorn ni `InternalErrorMiddleware`
  (`api/error_handlers.py`) lo leen, y este último solo deja método, ruta y tipo de error.
- Tampoco queda en el historial del navegador ni en la cabecera `Referer`.

**Alternatives considered**:

- **Query string con el registro de acceso apagado o filtrado**: depende de cómo se
  arranque uvicorn. Basta con un `--log-config` distinto para que el DNI se filtre.
- **Cabecera propia (`X-National-Id`)**: tampoco se registra, pero es menos habitual y
  algunos proxies la registran.
- **Huella (hash) del DNI en la URL**: un DNI tiene 10⁸ valores posibles, así que la huella
  se revierte por fuerza bruta en segundos. No protege nada.

## R2. Sin migración: la consulta se arma con lo que ya existe

**Decision**: una sola consulta en `StudyRepository`. Une `study`, `organ` y `patient`, y hace
un `left join lesion` agrupado por estudio:

- `count(l.lesion_id)` da el número de lesiones;
- `coalesce(sum(l.volume_mm3), 0)` da el volumen total;
- el filtro opcional es `p.national_id = %s`;
- el orden es `s.created_at desc, s.study_id desc`, con `limit`/`offset`.

**Rationale**:

- Todo el dato ya está en la base (`docs/database/schema/001_create_tables.sql`).
- La spec pide no guardar un total aparte (Assumptions), y un total guardado podría
  desalinearse de las lesiones.
- `patient.national_id` ya tiene índice, por su restricción `unique`, y `lesion.study_id`
  tiene `idx_lesion_study`.
- Con 500 estudios (SC-002), la agregación es trivial para PostgreSQL.

**Alternatives considered**:

- **Columna `study.total_lesion_volume_mm3`**: necesita migración y mantenerla al día.
  Se descarta por la regla de no guardar un total aparte.
- **Una consulta de lesiones por estudio (N+1)**: con 50 filas por página serían 51 idas a
  Supabase, y no cumpliría SC-002.
- **Índice sobre `study.created_at`**: no hace falta a esta escala. Se agrega si una
  medición lo justifica, nunca por adelantado.

## R3. Paginación por offset, con `has_more` leyendo una fila de más

**Decision**:

- `limit` por defecto 50, entre 1 y 100, y `offset` ≥ 0.
- El almacén pide `limit + 1` filas: si llegan más de `limit`, `has_more = true` y se
  devuelven solo `limit`.

**Rationale**:

- Es lo más simple para esta escala (cientos de estudios).
- No hace falta un `count(*)` aparte.
- El orden incluye `study_id` para desempatar, así ninguna fila se repite ni se salta entre
  páginas cuando dos estudios tienen la misma fecha.

**Alternatives considered**:

- **Paginación por cursor (keyset)**: es más robusta con muchas escrituras concurrentes,
  pero agrega un cursor opaco al contrato. Es innecesaria a esta escala.
- **Total de estudios en la respuesta**: la página solo necesita saber si hay más.

## R4. Solo un estudio `completed` tiene número de lesiones y volumen

**Decision**:

- El repositorio devuelve los conteos tal como están en la base.
- `StudyService.list_history` deja `lesion_count` y `total_lesion_volume_mm3` en `None` cuando
  el estado no es `completed`.
- Un `completed` sin lesiones da `0` y `0.0`.

**Rationale**:

- Es una regla del caso de uso (FR-008), no del acceso a datos.
- Un estudio `failed` después de la etapa 4 puede tener filas de lesión guardadas, y no
  deben mostrarse como resultado.
- Ponerla en el servicio la deja probada con dobles, sin base.
- Es un condicional por estado, no por órgano: el Principio II no lo prohíbe.

**Alternatives considered**: un `case when s.status = 'completed'` en el SQL. Funciona, pero
esconde la regla del negocio dentro de una consulta.

## R5. La API devuelve mm³; la web da formato con la misma función que el visor

**Decision**:

- La respuesta lleva `total_lesion_volume_mm3`, en la misma unidad que `volume_mm3` de
  `GET /studies/{code}/result`.
- `format_volume` sale de `index.html` a un módulo nuevo,
  `src/radvol3d/static/js/history_view.js`. Lo importan el visor y el historial.
- La función usa cm³ desde 1000 mm³ y mm³ por debajo, en español y con un decimal como
  máximo.

**Rationale**:

- SC-003 exige que el volumen del historial coincida con el del visor al redondeo mostrado.
  La única forma de garantizarlo es que los dos usen la misma función.
- A 128³ vóxeles en 320 mm, un vóxel mide unos 15,6 mm³, y muchas lesiones quedan por debajo
  de 1 cm³. Forzar cm³ con un decimal las mostraría como "0 cm³" o "< 0,1 cm³", y se perdería
  el dato.
- Esto ajusta la redacción de FR-007 ("en cm³"). La spec se actualiza para decir "con el
  mismo formato que el visor".

**Alternatives considered**:

- **Siempre cm³ con dos decimales**: se separa del visor e incumple SC-003.
- **Que la API devuelva cm³**: mezcla unidades entre rutas.

## R6. El historial deja de usar `localStorage`

**Decision**:

- Se quitan `read_history`, `write_history`, `remember` y `forget` de `index.html`.
- La lista, el retomar un estudio (`open_history_entry`) y el "último estudio terminado"
  del visor (`latest_completed_code`) se leen de `GET /studies`.
- Al cargar la página se borra una vez la clave vieja `radvol3d.history.v1`, dentro de
  `try/catch`.

**Rationale**:

- FR-004 dice que el navegador no es la fuente de las filas.
- Mantener dos fuentes haría que un estudio borrado en otro equipo siguiera apareciendo.
- La clave vieja no tiene datos personales, pero sí códigos de estudios que pueden no
  existir.

**Alternatives considered**: conservar `localStorage` como caché para mostrar algo sin red.
La spec pide lo contrario (FR-014: no mostrar filas viejas como si fueran actuales).

## R7. La lógica del historial se prueba con `node --test`

**Decision**: un módulo ES nuevo, `src/radvol3d/static/js/history_view.js`, servido en
`/static/js/history_view.js`. Contiene solo funciones puras:

- `format_volume`;
- `volume_text`, `national_id_text` y `lesion_count_text` de una fila;
- `clean_national_id` e `is_valid_national_id`.

Se prueba en `tests/unit/web/test_history_view.js`, que el CI ya corre con su patrón
`tests/unit/web/*.js`. `index.html` lo importa con `import ... from './js/history_view.js'`.

**Rationale**:

- El Principio IV exige una prueba unitaria y el CI ya tiene el ejecutor de Node sin npm
  (R14 de 004).
- La lógica que hoy vive dentro del `<script>` de `index.html` no se puede importar desde
  una prueba.

**Alternatives considered**:

- **Probar `index.html` desde Python, extrayendo el script**: es frágil y no ejecuta
  JavaScript.
- **Dejarlo sin prueba**: viola el Principio IV.

**Consecuencia**: abrir `index.html` como archivo suelto (`file://`) ya no carga el módulo.
No se pierde nada que funcione hoy: la API no tiene CORS configurado (`main.py`), así que
desde `file://` las llamadas a la API ya fallaban.

## R8. Excepción a FR-029 de 004, acotada y documentada

**Decision**:

- Solo los elementos del historial (`GET /studies` y `POST /studies/search`) llevan
  `national_id`. Nombre y apellido no salen nunca.
- Los esquemas de respuesta del historial no tienen campos para ellos, igual que
  `StudyResponse` hoy.
- `StudyHistoryEntry` declara `national_id` con `repr=False`, como `Patient`, para que no
  aparezca en trazas.
- Se actualizan el FR-029 de `specs/004-rest-api-viewer/spec.md` (con una nota que remite a
  esta spec) y `specs/004-rest-api-viewer/contracts/http_api.md` (FR-013).
- La página no escribe el DNI en la URL, en `localStorage` ni en la consola. El valor del
  filtro vive solo en memoria.

**Rationale**:

- El usuario aceptó mostrar el DNI completo sin autenticación (Clarifications, riesgo
  aceptado).
- Lo que sí se puede garantizar es que no salga por ningún otro lado.

**Alternatives considered**: enmascarar el DNI. Se descartó en la sesión de aclaraciones
(P2: A).
