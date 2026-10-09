# Feature Specification: Capa de servicios y tubería de procesamiento

**Feature Branch**: `feat/services-pipeline`

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Capa de servicios (services) de RadVol3D: interfaces Strategy
para reconstrucción, segmentación y mallas; fábrica de estrategias por órgano; tubería de
cuatro etapas registrada en persistence; StudyService con delete_study; conexión por lifespan;
estrategias reales que envuelven EN-1 y EN-2 sin cambiar su salida; pesos en Supabase Storage;
errores del dominio claros. Primero con estrategias falsas, los modelos reales al final."

## Clarifications

### Session 2026-10-09

- Q: ¿De dónde salen los pesos y los parámetros de operación de EN-2? → A: Un script
  documentado en `scripts/` genera una sola vez el `.pth` de exportación desde
  `models/en2_pulmon_mejor.pth`. Toma `parche` y `rejilla` del `cfg` del punto de control,
  fija `mm_por_voxel` en 2,5, y toma `umbral` 0,3, `min_voxeles` 10 y TTA de
  `models/metricas_test.json`. Su docstring dice de dónde sale cada valor. La estrategia EN-2
  sigue envolviendo `en2_inferencia.py` sin cambiar su lógica de carga. Si más adelante llega
  el `.pth` de exportación original, se reemplaza sin cambiar el código.
- Q: ¿Qué formatos acepta el preprocesamiento y si reescala algo? → A: Solo `.npy` en el
  convenio de TA-2 (integrales de línea, sin normalizar). Se validan la forma, los ángulos y
  que los valores sean finitos, sin reescalar. PNG se rechaza.
- Q: ¿De qué superficie sale la malla del órgano? → A: De la isosuperficie del volumen
  reconstruido, con un umbral calculado del propio volumen (Otsu). La malla depende de la
  calidad de la reconstrucción. Un umbral fijo en HU queda como mejora futura.
- Q: ¿Se amplía la persistencia con el borrado de estudios? → A: Sí (FR-015).
- Q: ¿Qué fecha de entrenamiento se registra? → A: Ninguna mientras no se conozca:
  `trained_on` queda vacío con `TODO(TRAINING_DATE_EN1)` y `TODO(TRAINING_DATE_EN2)`.

## User Scenarios & Testing *(mandatory)*

El actor directo es la capa de presentación (`api/`), que recibe los servicios ya armados y
nunca toca la persistencia. El beneficiario final es quien sube las cuatro radiografías de un
órgano y espera ver el volumen reconstruido, las lesiones detectadas y las mallas en el visor.
La persistencia ya existe (`specs/001-persistence-schema-migration/contracts/persistence_api.md`).
Hoy los servicios son archivos con `TODO`, y nada une las radiografías con el resultado.

### User Story 1 - Procesar un estudio de punta a punta con estrategias falsas (Priority: P1)

La capa de lógica recibe un estudio nuevo (código, órgano, datos opcionales del paciente y las
cuatro proyecciones a 0, 45, 90 y 135 grados). Con eso:

- registra el estudio y sus proyecciones en la persistencia;
- corre las cuatro etapas en orden: preprocesamiento, reconstrucción, segmentación y mallas;
- registra en la persistencia el estado, el inicio, el fin y el modelo de cada etapa;
- guarda el volumen, la máscara, la probabilidad, el resumen, las lesiones y las dos mallas;
- deja el estudio en `completed` con su tiempo total y lo devuelve.

En esta historia, las estrategias de reconstrucción, segmentación y mallas son dobles de prueba.

**Why this priority**: es la columna vertebral. Prueba el patrón Strategy, la fábrica, la
tubería y el servicio sin GPU, sin pesos y sin PyTorch. Si solo se entrega esta historia, el
sistema ya procesa estudios de punta a punta y cualquier estrategia real se enchufa después
sin tocar la tubería.

**Independent Test**: procesar un estudio de pulmón con los dobles contra la persistencia real
de prueba. Al pedir el estudio, vuelve en `completed`, con las cuatro etapas en `completed`,
cada una con inicio y fin, y con el modelo de reconstrucción y de segmentación registrados.
El resultado trae las cinco rutas y las lesiones del doble.

**Acceptance Scenarios**:

1. **Given** cuatro proyecciones válidas y el órgano `lung`, **When** la capa de lógica procesa
   el estudio, **Then** el estudio queda en `completed`, con `grid_size` 128, su tiempo total y
   el modelo de segmentación registrado.
2. **Given** un estudio en proceso, **When** se consulta su avance mientras corre, **Then**
   cada etapa muestra `waiting`, `running` o `completed` según por dónde vaya la tubería.
3. **Given** un estudio procesado, **When** se pide su resultado, **Then** vuelven las rutas de
   la máscara, la probabilidad, el resumen, la malla del órgano y la malla del tumor, más una
   lesión por cada región del resumen.
4. **Given** la tubería ya construida, **When** se cambia una estrategia por otra que cumple la
   misma interfaz, **Then** la tubería no se modifica.

---

### User Story 2 - Fallar con errores claros y sin datos del paciente (Priority: P1)

Si la entrada es inválida, un modelo no está disponible o una etapa falla, la capa de lógica
lanza un error del dominio que dice qué pasó, y el estudio queda en un estado consistente.

**Why this priority**: va con la historia 1. Sin estados consistentes, la interfaz consultaría
para siempre un estudio que ya murió. Sin mensajes limpios, un error podría filtrar el nombre o
el DNI del paciente a un registro o a la pantalla.

**Independent Test**: provocar cada error con los dobles (archivo ilegible, ángulo faltante,
ángulo repetido, órgano `liver`, una estrategia que lanza una excepción en la etapa 3). Cada
caso debe lanzar el error esperado. Ningún mensaje de error ni registro debe contener nombre,
apellido ni DNI.

**Acceptance Scenarios**:

1. **Given** tres proyecciones, o cuatro con un ángulo repetido, **When** se pide procesar,
   **Then** se lanza `InvalidProjectionError`, que nombra el ángulo faltante o repetido, y no
   se crea el estudio.
2. **Given** un archivo que no se puede leer como proyección, **When** se pide procesar,
   **Then** se lanza `InvalidProjectionError`, que nombra el ángulo afectado (no el contenido).
3. **Given** el órgano `liver`, **When** se pide la estrategia, **Then** se lanza
   `ModelNotAvailableError` con un mensaje que dice que no hay modelo de segmentación de hígado.
4. **Given** una estrategia que falla en la etapa N, **When** corre la tubería, **Then** la
   etapa N queda en `failed`, las siguientes en `skipped`, el estudio en `failed`, y se lanza un
   error del dominio que nombra la etapa sin incluir datos del paciente.
5. **Given** que los pesos de un modelo no se pudieron obtener al arrancar, **When** se pide
   procesar un estudio que lo necesita, **Then** se lanza `ModelNotAvailableError`.

---

### User Story 3 - Consultar y borrar estudios (Priority: P2)

La capa de lógica permite pedir un estudio, listar los recientes, pedir el resultado y borrar
un estudio con todo lo que tiene asociado.

**Why this priority**: consultar es necesario para que la interfaz muestre algo. Borrar es la
única forma de retirar un estudio de prueba o mal cargado. Sin borrado, los archivos quedan
huérfanos en el bucket. Hoy la persistencia no ofrece borrado: esta funcionalidad lo agrega.

**Independent Test**: procesar un estudio, borrarlo y comprobar que pedirlo lanza
`StudyNotFoundError` y que ningún archivo bajo su código queda en el bucket.

**Acceptance Scenarios**:

1. **Given** un estudio `completed`, **When** se borra, **Then** desaparecen el estudio, sus
   proyecciones, etapas y lesiones, y todos sus archivos del bucket. El paciente no se borra.
2. **Given** un código inexistente, **When** se borra, **Then** se lanza `StudyNotFoundError`.
3. **Given** un estudio en `processing`, **When** se pide borrarlo, **Then** se rechaza con un
   error del dominio y el estudio sigue intacto.
4. **Given** un estudio que existe pero no terminó, **When** se pide su resultado, **Then**
   vuelve un resultado vacío, sin error (comportamiento ya fijado en la persistencia).

---

### User Story 4 - Arrancar el servicio con todo conectado una sola vez (Priority: P2)

Al arrancar, la aplicación abre la base, prepara el almacenamiento, obtiene los pesos desde el
bucket de modelos, carga cada modelo una sola vez, registra cada modelo en la tabla `model` y
entrega a la presentación los servicios ya armados. Al apagarse, cierra la base.

**Why this priority**: cargar un modelo por petición agota la memoria y hace el servicio
inutilizable. Además, la presentación no puede importar la persistencia, así que alguien tiene
que armar los servicios por ella.

**Independent Test**: arrancar la aplicación con dobles en lugar de los modelos reales y
comprobar que cada estrategia se construyó una sola vez, que la presentación recibe el servicio
por inyección y que las pruebas de arquitectura siguen en verde.

**Acceptance Scenarios**:

1. **Given** la aplicación arrancada, **When** se procesan varios estudios, **Then** cada
   modelo se cargó una sola vez.
2. **Given** la aplicación, **When** se revisan los imports de `api/`, **Then** ninguno apunta
   a `persistence`, `psycopg`, `supabase` ni `torch`.
3. **Given** un modelo registrado al arrancar, **When** se consulta la tabla `model`, **Then**
   tiene una fila con su nombre y versión, y la fecha de entrenamiento es la real o queda vacía
   si no se conoce.

---

### User Story 5 - Reconstruir y segmentar con los modelos reales (Priority: P3)

Las estrategias reales reemplazan a los dobles:

- reconstrucción con EN-1;
- segmentación de pulmón con EN-2;
- mallas por marching cubes exportadas en `.glb`.

El código de `models/` se migra a la convención del proyecto (identificadores en inglés y
snake_case, comentarios y docstrings en español) sin cambiar su salida numérica.

**Why this priority**: es el valor final del sistema, pero va último a propósito. Depende de
que las historias 1 a 4 estén en verde, y es lo único que necesita PyTorch y los pesos.

**Independent Test**: con los pesos disponibles, procesar un estudio de ejemplo de pulmón y
obtener volumen, máscara, probabilidad, resumen y las dos mallas. Además, la prueba de
regresión compara la salida migrada de EN-1 y EN-2 con la salida de referencia de los scripts
originales sobre la misma entrada.

**Acceptance Scenarios**:

1. **Given** cuatro proyecciones de ejemplo, **When** corre la reconstrucción real, **Then**
   devuelve un volumen de 128 × 128 × 128 con valores en [0, 1].
2. **Given** ese volumen, **When** corre la segmentación real, **Then** devuelve una máscara
   binaria, una probabilidad en [0, 1] de la misma forma y un resumen con la estructura de
   `models/ejemplo_resumen.json`.
3. **Given** el resumen, **When** se guarda el resultado, **Then** cada elemento de `regions`
   es una fila de `lesion` con `location`, `volume_mm3`, `max_diameter_mm` y `confidence`.
4. **Given** la máscara y el volumen, **When** corre la etapa de mallas, **Then** se obtienen
   dos archivos `.glb` válidos: órgano y tumor.
5. **Given** la misma entrada de referencia, **When** se comparan la salida migrada y la
   original, **Then** coinciden dentro de la tolerancia fijada en FR-034.

---

### Edge Cases

- **Proyección en PNG u otro formato que no sea `.npy`**: `InvalidProjectionError`, que nombra
  el ángulo y dice que solo se acepta `.npy` en el convenio de TA-2. No se crea el estudio.
- **`.npy` con objetos serializados de Python**: se rechaza sin cargarlo, con
  `InvalidProjectionError`.
- **Volumen reconstruido constante o casi constante**: Otsu no puede separar dos clases. La
  malla del órgano se genera como `.glb` válido sin geometría y el estudio no falla por eso.
- **Proyección con NaN o infinitos**: `InvalidProjectionError` en el preprocesamiento, antes de
  crear el estudio.
- **Proyección con forma distinta de 128 × 128**: `InvalidProjectionError`, que nombra el
  ángulo y la forma esperada.
- **Volumen fuera de [0, 1] al llegar a la segmentación**: la segmentación lo rechaza, la etapa
  3 queda en `failed` (el modelo EN-2 ya valida esto y no se relaja).
- **Segmentación sin lesión**: la máscara está vacía, `regions` es `[]` y no se crean filas de
  `lesion`. La malla del tumor se genera igual como archivo `.glb` válido sin geometría, para
  que el visor no tenga que distinguir el caso.
- **Dos estudios a la vez**: cada uno obtiene su propio volumen, máscara, resumen y mallas.
  Ningún dato de uno aparece en el otro, aunque compartan los modelos cargados.
- **El mismo código de estudio dos veces**: la segunda vez se lanza `DuplicateStudyError` y el
  primero no se toca.
- **Falla la subida al bucket a mitad de la tubería**: la etapa en curso queda en `failed`, el
  estudio en `failed`, y los archivos ya subidos quedan para diagnóstico. `delete_study` los
  limpia.
- **Borrar un estudio `failed`**: se permite y limpia todo lo que haya quedado.
- **Pesos ausentes o corruptos en el bucket al arrancar**: la aplicación arranca igual, el
  arranque deja escrito qué modelo falta, y los estudios que lo necesitan fallan con
  `ModelNotAvailableError`.

## Requirements *(mandatory)*

### Functional Requirements

**Interfaces y fábrica (Strategy y Factory Method)**

- **FR-001**: Cada una de las tres etapas variables (reconstrucción, segmentación, mallas) MUST
  tener una interfaz única. Toda implementación de una etapa MUST cumplir la misma firma y
  exponer el nombre y la versión del modelo con que se registra en la tabla `model`.
- **FR-002**: MUST existir dobles de prueba de las tres interfaces en `tests/fixtures/`. Los
  dobles no cargan PyTorch, pesos ni GPU y responden en milisegundos.
- **FR-003**: La elección de estrategia según la configuración y el órgano MUST hacerse en un
  solo lugar, la fábrica. La tubería y los servicios MUST NOT contener condicionales por órgano.
- **FR-004**: Si se pide una estrategia para `liver`, la fábrica MUST lanzar
  `ModelNotAvailableError` con un mensaje que dice que el modelo de hígado no existe todavía.
- **FR-005**: La configuración MUST permitir elegir el algoritmo de reconstrucción sin tocar el
  código. Por omisión se usa EN-1.

**Tubería (Pipes and Filters)**

- **FR-006**: La tubería MUST encadenar las cuatro etapas en orden fijo: 1 preprocesamiento,
  2 reconstrucción, 3 segmentación, 4 mallas. Cada etapa recibe solo la salida de la anterior.
- **FR-007**: Al empezar cada etapa, la tubería MUST marcarla `running` en la persistencia. Al
  terminar, MUST marcarla `completed`. Cada etapa registra su inicio y su fin. Las etapas 2 y 3
  MUST registrar además el modelo que usaron.
- **FR-008**: Si una etapa falla, la tubería MUST marcarla `failed`, marcar las siguientes
  `skipped`, poner el estudio en `failed` y lanzar un error del dominio que nombre la etapa.
- **FR-009**: Al terminar las cuatro etapas, el estudio MUST quedar en `completed`, con el
  modelo de segmentación, el tamaño de rejilla y el tiempo total medido de punta a punta.
- **FR-010**: El preprocesamiento MUST validar que lleguen exactamente cuatro proyecciones, una
  por cada ángulo de `config.PROJECTION_ANGLES`, sin repetidos ni faltantes. Cada una debe ser
  legible, 128 × 128 y finita. Devuelve el arreglo (4, 128, 128) float32 ordenado por ángulo.
- **FR-011**: El preprocesamiento MUST aceptar solo `.npy` numéricos (sin objetos serializados)
  en el convenio de TA-2: integrales de línea del volumen normalizado, haz paralelo, sin
  normalizar por el espesor. MUST NOT reescalar ni normalizar los valores. Un PNG o cualquier
  otro formato MUST rechazarse con `InvalidProjectionError`, que nombra el ángulo y el formato
  aceptado. `config.ACCEPTED_FORMATS` y los docstrings que hoy dicen "float32 en [0, 1]" para
  las proyecciones (preprocesamiento e interfaz de reconstrucción) se corrigen en el mismo
  cambio.

**Servicio de estudios**

- **FR-012**: `StudyService` MUST recibir sus dependencias (almacenes de la persistencia y
  tubería) por su constructor. No las construye ni las busca.
- **FR-013**: `StudyService` MUST ofrecer: procesar un estudio nuevo, pedir un estudio, listar
  los recientes, pedir el resultado y borrar un estudio.
- **FR-014**: Procesar un estudio MUST, en este orden: validar la entrada (FR-010), registrar el
  estudio con sus proyecciones, correr la tubería, guardar el volumen y el resultado, y devolver
  el estudio terminado.
- **FR-015**: La persistencia MUST ganar una operación de borrado de estudio. Esa operación
  borra en una sola unidad de trabajo las filas de `lesion`, `processing_stage`, `projection` y
  `study`, y después todos los archivos bajo el código del estudio en el bucket. El paciente y
  los modelos no se borran. El contrato de `persistence_api.md` se amplía en el mismo cambio.
- **FR-016**: `delete_study` MUST lanzar `StudyNotFoundError` si el estudio no existe y MUST
  rechazar el borrado de un estudio en `processing` con un error del dominio propio.

**Conexión al arrancar**

- **FR-017**: Al arrancar, la aplicación MUST abrir la base, preparar el almacenamiento, obtener
  los pesos del bucket de modelos, construir cada estrategia una sola vez y armar
  `StudyService`. Al apagarse, MUST cerrar la base.
- **FR-018**: El armado de los servicios MUST vivir en `services/` (o en el punto de entrada),
  nunca en `api/`. La presentación MUST recibir el servicio con `Depends()`.
- **FR-019**: Si los pesos de un modelo no se pueden obtener o cargar, el arranque MUST dejar
  constancia de qué modelo falta (sin la clave del bucket) y la aplicación MUST seguir
  arrancando. Los estudios que lo necesiten MUST fallar con `ModelNotAvailableError`.
- **FR-020**: Varios estudios procesados a la vez MUST compartir los modelos cargados sin
  mezclar sus datos intermedios ni sus resultados.

**Estrategias reales (último bloque)**

- **FR-021**: La reconstrucción real MUST envolver el módulo de inferencia de EN-1 con sus
  pesos. Recibe (4, 128, 128) y devuelve (128, 128, 128) float32 en [0, 1].
- **FR-022**: La segmentación real de pulmón MUST envolver el módulo de inferencia de EN-2, que
  define la red dentro del mismo archivo. Devuelve máscara uint8 binaria, probabilidad float32
  en [0, 1] de la misma forma, y un resumen con la estructura de `models/ejemplo_resumen.json`.
- **FR-023**: La segmentación real MUST cargar un `.pth` de exportación con el formato que exige
  `en2_inferencia.py` (`pesos`, `canales`, `umbral`, `min_voxeles`, `parche`, `tta`, `rejilla`
  y `mm_por_voxel` en el primer nivel). Hoy ese archivo no existe: `models/en2_pulmon_mejor.pth`
  es un punto de control de entrenamiento (`modelo`, `epoca`, `dice_val`, `cfg`, `canales`).
  Por eso MUST existir un script en `scripts/` que lo genere una sola vez:
  - `pesos` ← `modelo` del punto de control; `canales` ← `canales` del punto de control;
  - `parche` y `rejilla` ← `cfg` del punto de control;
  - `mm_por_voxel` ← 2,5 (`config.MM_PER_VOXEL`);
  - `umbral` 0,3, `min_voxeles` 10 y `tta` ← `models/metricas_test.json`.
  El docstring del script MUST decir de dónde sale cada valor. El script no infiere, no
  entrena ni cambia los pesos. El `.pth` generado se sube al bucket de modelos como cualquier
  otro peso. Si llega el `.pth` de exportación original, se reemplaza en el bucket sin cambiar
  el código, y la referencia de regresión de EN-2 (FR-034) se regenera.
- **FR-023a**: La estrategia EN-2 MUST envolver `en2_inferencia.py` sin cambiar su lógica de
  carga ni de inferencia. La alineación de identificadores de FR-025 se hace en la estrategia,
  sobre el resumen ya calculado, para que funcione igual con el `.pth` generado y con el
  original.
- **FR-024**: Cada elemento de `summary["regions"]` MUST generar una fila de `lesion` con
  `location`, `volume_mm3`, `max_diameter_mm` y `confidence`. El `mesh_path` de cada fila apunta
  a la malla del tumor del estudio (regla ya fijada en la persistencia).
- **FR-025**: En el resumen, los identificadores de texto MUST quedar en inglés y alineados con
  el dominio: el órgano como `lung`, el código del estudio en lugar de `study_id`, y el nombre y
  la versión del modelo iguales a los registrados en `model`. Los textos para el usuario
  (`location`, `location_note`) siguen en español. Los valores numéricos no cambian.
- **FR-026**: La etapa de mallas MUST producir dos archivos `.glb` por estudio con marching
  cubes y solo con bibliotecas gratuitas. Las coordenadas MUST estar en milímetros, con 2,5 mm
  por vóxel:
  - la malla del tumor, desde la máscara de segmentación;
  - la malla del órgano, desde la isosuperficie del volumen reconstruido, con un umbral
    calculado del propio volumen por el método de Otsu. No se fija ningún valor a mano.
- **FR-026a**: La malla del órgano depende de la calidad de la reconstrucción: si el volumen
  sale borroso, la superficie también. Esto se documenta en `docs/models/`. Un umbral fijo en
  HU con fuente citada queda como mejora futura.
- **FR-027**: Al migrar los archivos de `models/`, MUST renombrarse los archivos y los
  identificadores al inglés y snake_case (por ejemplo, `SegmentadorPulmon.segmentar` pasa a
  `LungSegmenter.segment` y `ReconstructorEN1.reconstruir` a `En1Reconstructor.reconstruct`).
  Los comentarios y docstrings MUST quedar en español con el formato de la convención. Las
  operaciones, su orden y las constantes numéricas MUST NOT cambiar.
- **FR-028**: Los archivos de pesos MUST NOT entrar al repositorio. Viven en un bucket de
  modelos de Supabase Storage. El nombre del bucket y las rutas de los pesos se leen de la
  configuración.
- **FR-029**: Cada modelo MUST registrarse en la tabla `model` con nombre y versión. La fecha
  de entrenamiento MUST ser la real. Si no se conoce, queda vacía y se registra como pregunta
  abierta. MUST NOT estimarse. `models/metricas_test.json` se usa solo para documentar el
  modelo en `docs/models/`.
- **FR-030**: Las nuevas dependencias pesadas (PyTorch, scikit-image, trimesh) MUST declararse
  con su peso y su motivo en el pull request y en el plan.

**Errores**

- **FR-031**: La capa de lógica MUST lanzar solo errores de `domain/exceptions.py`: archivo
  inválido, ángulo faltante o repetido, modelo no disponible, fallo de una etapa y borrado
  rechazado. Los errores nuevos que hagan falta (fallo de etapa, borrado rechazado) se agregan
  ahí, con su prueba.
- **FR-032**: Ningún mensaje de error ni registro MUST contener nombre, apellido ni DNI del
  paciente, ni el contenido de los archivos. Solo el código del estudio, el ángulo o la etapa.

**Pruebas**

- **FR-033**: MUST existir pruebas:
  - unitarias de cada estrategia, la fábrica y cada etapa, con los dobles;
  - de integración de la tubería completa contra la persistencia real de prueba;
  - de concurrencia con dos estudios a la vez sin mezclar resultados;
  - de arquitectura: las reglas de capas existentes siguen en verde y no se modifican.
- **FR-034**: MUST existir una prueba de regresión numérica de EN-1 y EN-2. Compara la salida
  migrada con una salida de referencia generada una sola vez con los scripts originales, antes
  de renombrar nada, sobre una entrada determinista sin datos de pacientes. La máscara MUST
  coincidir exactamente. El volumen y la probabilidad MUST coincidir con una diferencia absoluta
  máxima de 1e-5 en CPU. El resumen MUST coincidir campo por campo, salvo los identificadores
  de texto de FR-025.
- **FR-035**: Las pruebas que necesitan PyTorch o pesos MUST llevar un marcador propio,
  registrado en `pyproject.toml`, para poder omitirlas. Ninguna prueba `unit` carga PyTorch.

### Key Entities

- **Estrategia de reconstrucción**: convierte cuatro proyecciones en un volumen. Expone el
  nombre y la versión del modelo. Implementaciones: EN-1 (real) y el doble.
- **Estrategia de segmentación**: convierte un volumen en máscara, probabilidad, confianza
  global, lesiones y resumen. Una por órgano. Implementaciones: EN-2 de pulmón (real) y el
  doble. Hígado no existe todavía.
- **Estrategia de mallas**: convierte una máscara o un volumen en un archivo `.glb`.
  Implementaciones: marching cubes (real) y el doble.
- **Fábrica de estrategias**: único lugar que sabe qué estrategia corresponde a cada órgano y
  configuración.
- **Tubería**: las cuatro etapas encadenadas. Registra cada etapa en la persistencia y no sabe
  qué estrategias le tocaron.
- **Servicio de estudios**: caso de uso que valida, registra, procesa, consulta y borra
  estudios. Es lo único que la presentación ve.
- **Resumen de segmentación**: documento por estudio con las claves de
  `models/ejemplo_resumen.json`. Cada región con lesión se vuelve una `lesion`.
- **Modelo**: fila de `model` (nombre, versión, fecha real de entrenamiento o vacía). Se
  enlaza a las etapas 2 y 3 y al estudio.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un estudio procesado con los dobles termina en `completed`, con sus cuatro etapas
  registradas y sus cinco archivos de resultado guardados, en el 100 % de las corridas de la
  prueba de integración.
- **SC-002**: La suite de pruebas unitarias de servicios corre completa en menos de 10 segundos
  en una laptop sin GPU, porque ninguna carga modelos.
- **SC-003**: Con los modelos reales, un estudio de ejemplo produce volumen, máscara,
  probabilidad, resumen y las dos mallas, y el visor puede abrir ambas mallas.
- **SC-004**: La salida migrada de EN-1 y EN-2 coincide con la de referencia dentro de la
  tolerancia de FR-034 en el 100 % de los casos de referencia.
- **SC-005**: Dos estudios procesados a la vez terminan con resultados idénticos a los que
  obtienen cuando se procesan por separado, en 20 corridas seguidas sin fallar.
- **SC-006**: Cada modelo se carga exactamente una vez por arranque, sin importar cuántos
  estudios se procesen.
- **SC-007**: Ningún mensaje de error de la capa de lógica contiene datos personales del
  paciente. La prueba lo verifica sobre todos los errores provocados en la historia 2.
- **SC-008**: El análisis de estilo, la verificación de nombres y las pruebas pasan sin
  errores, y la cobertura de `services/` es de al menos 80 %.
- **SC-009**: Agregar un órgano nuevo requiere agregar una estrategia y una entrada en la
  fábrica, sin tocar la tubería ni el servicio.

## Assumptions

- **Orden de construcción**: primero las historias 1 a 4 con los dobles y todas las pruebas en
  verde. La historia 5 (modelos reales) es el último bloque.
- **Archivo de EN-1**: el archivo real se llama `models/en1_inferencia_nuevo (1).py` y sus pesos
  `models/en1_pesos_liviano (2).pth`. La descripción decía `en1_inferencia.py`. Se asume que es
  el mismo módulo. El punto de control trae solo `mejores_pesos`, así que los parámetros de
  operación (rejilla, filtro, calibraciones) salen de las constantes del módulo, como hoy.
- **Fecha de entrenamiento**: ninguno de los dos archivos de pesos trae una fecha y el
  repositorio tampoco la registra. Mientras nadie la aporte, `trained_on` queda vacío y se deja
  `TODO(TRAINING_DATE_EN1)` y `TODO(TRAINING_DATE_EN2)` (Principio V).
- **Ejecución**: `StudyService` corre la tubería dentro de la llamada que la pide. Decidir si la
  presentación lo lanza en segundo plano es parte de la capa `api`, fuera de alcance.
- **Concurrencia**: los modelos se comparten entre estudios en modo inferencia, sin estado entre
  llamadas. Si una inferencia simultánea no es segura, se serializa el acceso al modelo, no se
  carga una copia por estudio.
- **Borrado**: se borran solo el estudio y lo que cuelga de él. El paciente se conserva porque
  puede tener otros estudios. Se permite borrar estudios `pending`, `completed` y `failed`.
- **Archivos tras un fallo**: lo ya subido al bucket se conserva para diagnóstico hasta que se
  borre el estudio.
- **Arranque sin pesos**: la aplicación arranca aunque falte un modelo, para que la salud del
  servicio y la consulta de estudios sigan funcionando.
- **Referencia de regresión**: se genera con los scripts originales y la entrada determinista
  de sus propias autopruebas (el fantoma elipsoide de EN-1 y el volumen sintético de EN-2), en
  CPU. La de EN-2 usa el `.pth` de exportación generado por el script de FR-023. El formato y el lugar donde se guarda la referencia se deciden en el plan. Si pesa
  demasiado para el repositorio, va al bucket.
- **Cobertura**: se mide como la mide hoy la integración continua. Para que la parte que no usa
  PyTorch (geometría, filtro, resumen por regiones, mallas) cuente en la cobertura sin cargar
  PyTorch, esa parte se separa de las clases que sí lo usan.
- **Estrategias fuera de alcance**: `BackprojectionStrategy` y `LiverUnetStrategy` siguen como
  esqueletos. La fábrica no ofrece hígado.

## Out of Scope

- Endpoints y esquemas HTTP de la capa `api`.
- Visor web 3D.
- Reentrenamiento de modelos.
- Modelo de hígado.
- Malla por lesión (`lesion_<region_id>.glb`), ya reservada en la persistencia.
- Calibración de radiografías clínicas reales al convenio de TA-2, y con ella la entrada en
  PNG.
- Umbral fijo en HU para la malla del órgano (mejora futura, FR-026a).
- Segmentación del órgano completo.
