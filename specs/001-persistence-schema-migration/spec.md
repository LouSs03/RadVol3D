# Feature Specification: Migración de la capa de persistencia al esquema en inglés

**Feature Branch**: `001-persistence-schema-migration`

**Created**: 2026-10-08

**Status**: Draft

**Input**: User description: "Migrar la capa de persistencia al esquema nuevo en inglés: settings, connection, storage_layout, object_storage y los seis repositorios. Qué debe hacer cada uno, no cómo."

## Clarifications

### Session 2026-10-08

- Q: ¿Cómo se asocia el paciente a un estudio? → A: Se agrega un séptimo repositorio,
  `patient`, porque la interfaz va a pedir nombre, apellido y DNI. El repositorio busca al
  paciente por DNI y lo crea si no existe. Si el DNI ya existe, reutiliza la fila. Si no hay
  datos personales, el estudio se asocia a `PAC000000`. Los tres campos son opcionales y el DNI
  es único cuando se registra.
- Q: ¿Qué formato tienen las rutas dentro del bucket? → A: Van bajo el código del estudio:
  `projections/angle_000.npy` (y `045`, `090`, `135`), `volume.npy`, `segmentation/mask.npy`,
  `segmentation/probability.npy`, `segmentation/summary.json`, `meshes/organ.glb` y
  `meshes/tumor.glb`. Se rechazan `..`, la barra invertida y la cadena vacía.
- Q: ¿Qué guarda el bucket? → A: Las proyecciones, el volumen reconstruido, las máscaras y las
  mallas. La base guarda solo las rutas, nunca los binarios. Todos los arreglos se guardan como
  `.npy` sin objetos serializados de Python.
- Q: ¿Entran `study_metadata_store.py` y `result_store.py`? → A: Sí, los dos. Dejar la capa a
  medias obliga a una segunda migración.
- Q: ¿Se agregan los campos que faltan en el dominio? → A: Sí. A `Study` se le agregan el
  paciente, el modelo y el tamaño de rejilla, y a `ProcessingStage` el modelo.
- Q: ¿Hay metas de rendimiento? → A: No. No se inventan.
- Q: ¿Cada lesión tiene su propia malla? → A: Por ahora no. Un solo archivo,
  `<study_code>/meshes/tumor.glb`, contiene todas las lesiones, y el `mesh_path` de cada fila
  apunta a él. La ruta `<study_code>/meshes/lesion_<region_id>.glb` queda reservada para cuando
  el visor necesite encender y apagar lesiones por separado. No se implementa ahora.
- Q: ¿Qué formato tiene el código de los pacientes nuevos? → A: `PAC` más seis dígitos, igual
  que `PAC000000`. El repositorio de pacientes genera el siguiente consecutivo al crear uno
  nuevo y valida el formato `^PAC[0-9]{6}$`.
- Q: ¿Qué contiene `summary.json`? → A: Lo produce el módulo de inferencia de segmentación.
  Están las claves de primer nivel y las diez de cada elemento de `regions` (ver FR-050).
- Q: ¿`regions` incluye regiones sin lesión? → A: No. Solo trae regiones con lesión. Si no hay
  lesión, `regions` es `[]` y `has_lesion` del nivel superior es `false`. Cada elemento de
  `regions` genera una fila de `lesion`. La comprobación de `has_lesion` queda como defensa, no
  como filtro real.
- Q: ¿Qué devuelve la consulta del resultado si el estudio existe pero todavía no tiene
  resultado guardado? → A: Un resultado vacío, sin error: todas las rutas en `None` y la lista
  de lesiones vacía. La interfaz consulta mientras el estudio se procesa, así que un error ahí
  sería un falso fallo. Solo lanza `StudyNotFoundError` si el estudio no existe.

## User Scenarios & Testing *(mandatory)*

El actor directo de esta funcionalidad es la capa de lógica (`services/`), que guarda y lee
estudios a través de la persistencia. El beneficiario final es la persona que carga los datos
del paciente y sus cuatro radiografías, y espera ver el órgano reconstruido con sus lesiones.
Sin persistencia, nada de lo que hace la tubería sobrevive a la petición.

Hoy los doce componentes de `persistence/` existen solo como archivos con un `TODO`. El esquema
en inglés ya está aplicado en la base (`docs/database/schema/001_create_tables.sql`). Las tablas
del esquema anterior, en español, se eliminaron.

### User Story 1 - Registrar un estudio con su paciente y sus cuatro proyecciones (Priority: P1)

La capa de lógica recibe los datos personales del paciente, todos opcionales, y cuatro
radiografías de un órgano. Con eso:

- identifica al paciente o lo registra;
- crea el estudio en estado `pending`;
- guarda cada proyección en el bucket y registra su ruta en la base.

Después se puede pedir el estudio por su código.

**Why this priority**: es la puerta de entrada de todo el sistema. Para usarla hacen falta la
configuración, la conexión, las rutas, el almacenamiento de objetos, el almacén de metadatos y
los repositorios `patient`, `organ`, `study`, `projection` y `processing_stage`. Si solo se
entrega esta historia, el sistema ya acepta y conserva estudios.

**Independent Test**: registrar un estudio de pulmón con DNI y cuatro proyecciones y pedirlo de
nuevo por su código. Debe volver con su paciente, el órgano, el estado `pending`, las cuatro
proyecciones ordenadas por ángulo y las cuatro etapas en `waiting`. Cada proyección se tiene que
poder descargar desde su ruta.

**Acceptance Scenarios**:

1. **Given** un código de estudio que no existe y el órgano `lung`, **When** se registra el
   estudio con proyecciones en 0, 45, 90 y 135 grados, **Then** el estudio queda en `pending`.
   Las proyecciones quedan en `<study_code>/projections/angle_000.npy`, `angle_045.npy`,
   `angle_090.npy` y `angle_135.npy`, y al pedir el estudio vuelven con su ruta y su nombre
   original.
2. **Given** un DNI que no está registrado, **When** se registra un estudio con nombre, apellido
   y ese DNI, **Then** se crea un paciente nuevo con un código interno propio y el estudio queda
   asociado a él.
3. **Given** un DNI ya registrado, **When** se registra otro estudio con ese DNI, **Then** se
   reutiliza el paciente existente y no se crea una fila nueva.
4. **Given** que no se envía ningún dato personal, **When** se registra el estudio, **Then**
   queda asociado al paciente de referencia `PAC000000`.
5. **Given** un DNI que no tiene exactamente ocho dígitos, **When** se intenta registrar,
   **Then** se rechaza con un error del dominio antes de crear el estudio.
6. **Given** un estudio ya registrado, **When** se intenta registrar otro con el mismo código,
   **Then** la operación se rechaza con un error del dominio y el estudio original no cambia.
7. **Given** un código con caracteres no permitidos, `..`, una barra invertida o una cadena
   vacía, **When** se intenta registrar o consultar, **Then** se rechaza con el error de
   identificador inválido antes de tocar la base o el almacenamiento.
8. **Given** un código que no existe, **When** se pide el estudio, **Then** se obtiene el error
   de estudio inexistente.
9. **Given** una proyección con un ángulo fuera de {0, 45, 90, 135} o un ángulo repetido,
   **When** se intenta guardar, **Then** se rechaza con el error de proyección inválida.

---

### User Story 2 - Seguir el avance del procesamiento (Priority: P2)

Mientras la tubería procesa un estudio, la capa de lógica registra en qué etapa va y cómo
terminó cada una. Las etapas son preprocesamiento, reconstrucción, segmentación y mallas. La
capa también registra el estado general del estudio, el modelo usado y el volumen reconstruido.
Si el proceso falla a mitad de camino, el registro muestra hasta dónde llegó.

**Why this priority**: sin esto un estudio que falla es indistinguible de uno que nunca empezó.
Depende de la historia 1 (necesita un estudio registrado) y agrega el repositorio `model`.

**Independent Test**: sobre un estudio registrado, avanzar las etapas 1 y 2 hasta `completed` y
guardar el volumen reconstruido. Después marcar la 3 como `failed` y el estudio como `failed`.
Al consultar, las etapas 1 y 2 tienen que aparecer con inicio y fin, la 3 como fallida y la 4 en
espera, y el volumen se tiene que poder descargar desde `<study_code>/volume.npy`.

**Acceptance Scenarios**:

1. **Given** un estudio recién registrado, **When** se consultan sus etapas, **Then** existen
   exactamente cuatro, numeradas del 1 al 4, todas en `waiting`.
2. **Given** una etapa en `waiting`, **When** se marca como en curso y luego como terminada,
   **Then** queda con su hora de inicio y su hora de fin, y el fin no es anterior al inicio.
3. **Given** un modelo con nombre y versión, **When** se registra dos veces el mismo par,
   **Then** el catálogo conserva una sola fila y ambas llamadas devuelven el mismo modelo.
4. **Given** un estudio procesado con éxito, **When** se cierra, **Then** el estudio queda en
   `completed` con el modelo de reconstrucción, el tamaño de rejilla y el tiempo total.

---

### User Story 3 - Guardar y consultar los resultados de la segmentación (Priority: P3)

Al terminar la segmentación y la generación de mallas, la capa de lógica entrega los resultados
del estudio, y la persistencia guarda en una sola operación:

- la máscara, la probabilidad y el resumen por región;
- las mallas del órgano y del tumor;
- las filas de lesiones;
- las etapas 3 y 4 marcadas como completadas.

El visor puede pedir todo eso después.

**Why this priority**: es el resultado clínico del sistema. Depende de las historias 1 y 2.
Agrega el repositorio `lesion` y el almacén de resultados.

**Independent Test**: sobre un estudio con las etapas 1 y 2 completadas, guardar un resultado
con dos lesiones. Al pedirlo de nuevo, las lesiones tienen que volver con los mismos valores,
los cinco archivos del resultado tienen que poder descargarse y las etapas 3 y 4 tienen que
estar en `completed`.

**Acceptance Scenarios**:

1. **Given** un estudio registrado y un resultado de segmentación, **When** se guarda el
   resultado, **Then** existen `segmentation/mask.npy`, `segmentation/probability.npy`,
   `segmentation/summary.json`, `meshes/organ.glb` y `meshes/tumor.glb` bajo el código del
   estudio, las lesiones quedan registradas y las etapas 3 y 4 quedan en `completed`.
2. **Given** una lesión con volumen cero o negativo, o con confianza fuera de [0, 1],
   **When** se intenta guardar el resultado, **Then** se rechaza con un error del dominio, no se
   guarda ninguna lesión del lote y las etapas 3 y 4 no se marcan como completadas.
3. **Given** una lesión sin diámetro máximo, **When** se guarda, **Then** se acepta y el campo
   queda vacío. No se le asigna un valor estimado.
4. **Given** un arreglo guardado como `.npy`, **When** se lee de vuelta, **Then** se obtiene el
   mismo arreglo, y la lectura rechaza cualquier archivo que contenga objetos serializados de
   Python.
5. **Given** un resultado sin lesiones (`has_lesion: false`, `regions: []`), **When** se guarda,
   **Then** se guardan los archivos y el resumen, no se crea ninguna fila de `lesion` y las
   etapas 3 y 4 quedan en `completed`.
6. **Given** un resumen con tres elementos en `regions`, **When** se guarda el resultado,
   **Then** existen exactamente tres filas de `lesion`. Cada una lleva la ubicación, el volumen,
   el diámetro máximo y la confianza media de su región.
7. **Given** un estudio registrado que todavía no tiene resultado guardado (por ejemplo, porque
   se está procesando), **When** se consulta su resultado, **Then** se obtiene un resultado
   vacío, con todas las rutas en `None` y la lista de lesiones vacía, y no se lanza ningún
   error.
8. **Given** un código de estudio que no existe, **When** se consulta su resultado, **Then**
   se obtiene el error de estudio inexistente.

---

### User Story 4 - Arrancar con configuración válida o no arrancar (Priority: P4)

Quien despliega o desarrolla el sistema copia `.env.example` como `.env` y completa los valores.
Si falta alguno o la base no responde, el sistema lo dice al arrancar, en español, sin mostrar
ninguna clave.

**Why this priority**: la historia 1 ya necesita configuración y conexión válidas. Esta historia
cubre los casos de error, que son los que hoy dejan al equipo adivinando.

**Independent Test**: arrancar sin `SUPABASE_SERVICE_KEY` y comprobar que el sistema no arranca
y que el mensaje nombra la variable faltante. Arrancar con la base inaccesible y comprobar que
se obtiene el error de base no disponible. En ningún caso debe aparecer el valor de una clave.

**Acceptance Scenarios**:

1. **Given** un `.env` al que le falta una variable obligatoria, **When** el sistema arranca,
   **Then** se detiene y el mensaje en español nombra la variable que falta.
2. **Given** una base de datos inaccesible, **When** el sistema arranca o hace una consulta,
   **Then** se obtiene el error de base de datos no disponible, con un mensaje en español.
3. **Given** cualquier error de configuración, conexión o almacenamiento, **When** se muestra o
   se registra, **Then** el texto no contiene el valor de ninguna credencial.

---

### Edge Cases

- **El archivo se sube pero la fila no se guarda, o al revés.** Un fallo en la base después de
  subir el archivo no puede dejar el estudio a medio registrar como si estuviera completo.
- **Registro a medias.** Si falla una de las cuatro proyecciones, no quedan las otras tres
  registradas como un estudio válido.
- **DNI conocido con nombre distinto.** Se reutiliza el paciente existente tal como está. Sus
  datos registrados no se sobrescriben.
- **Nombre o apellido sin DNI.** No hay con qué identificar al paciente, así que se crea un
  paciente nuevo con esos datos. No se busca por nombre.
- **Dos pacientes nuevos a la vez.** Dos registros simultáneos no pueden recibir el mismo
  código consecutivo.
- **Se agotan los códigos.** Si el siguiente consecutivo pasara de `PAC999999`, el registro
  falla con un error del dominio. Nunca se genera un código fuera del formato.
- **Datos personales en mensajes.** El DNI, el nombre y el apellido no aparecen en los mensajes
  de error ni en los registros.
- **Etapa marcada como terminada sin haber empezado.** Se rechaza o se registra sin hora de
  inicio. Nunca se inventa una hora de inicio.
- **Etapa duplicada.** Preparar las etapas dos veces para el mismo estudio no crea ocho filas.
- **Órgano fuera del alcance.** Un estudio para un órgano distinto de `lung` o `liver` se
  rechaza con un error del dominio.
- **Archivo inexistente.** Pedir un archivo que no existe en el almacenamiento produce un error
  de almacenamiento distinguible de un fallo de red o de permisos.
- **Conexión perdida a mitad de operación.** Se traduce al error de base no disponible y no deja
  cambios parciales confirmados.
- **Consulta durante el procesamiento.** La interfaz pide el resultado mientras el estudio se
  procesa. Eso no es un fallo: se responde con el resultado vacío (FR-049).
- **Guardado de resultado fallido.** Si un guardado falló después de subir algún archivo, esos
  archivos sueltos no cuentan como resultado guardado. La consulta sigue devolviendo el
  resultado vacío.
- **Esquema anterior.** Ningún componente intenta leer ni escribir las tablas en español
  (`paciente`, `estudio`, `proyeccion`, `lesion_detectada`, etc.).

## Requirements *(mandatory)*

### Functional Requirements

**Comunes a toda la capa**

- **FR-001**: Todos los componentes de la capa MUST usar exclusivamente las tablas y columnas del
  esquema en inglés de `docs/database/schema/001_create_tables.sql`. Ningún componente MUST
  referirse a nombres del esquema anterior.
- **FR-002**: La capa MUST entregar a las capas superiores entidades y errores del dominio
  (`domain/`). Nunca debe entregar filas, diccionarios sueltos ni errores propios de la base o
  del almacenamiento.
- **FR-003**: Toda violación de una restricción del esquema (unicidad, formato, rango, valores
  permitidos, clave foránea) MUST traducirse a un error del dominio con mensaje en español.
- **FR-004**: La capa MUST NOT depender de nada de la capa de presentación (constitución,
  Principio I).
- **FR-005**: Las operaciones que tocan varias filas o tablas como una unidad MUST confirmarse
  todas o ninguna. Ejemplos: registrar un estudio con su paciente y sus proyecciones, preparar
  las cuatro etapas y guardar un resultado con sus lesiones y etapas.
- **FR-006**: La base de datos MUST guardar solo rutas a archivos del bucket, nunca su contenido
  binario.

**Configuración (`settings`)**

- **FR-007**: MUST leer `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` y
  `STORAGE_BUCKET` desde el archivo `.env` de la raíz o desde el entorno. Son las variables de
  `.env.example`. Ningún valor MUST estar escrito en el código.
- **FR-008**: Si falta una variable obligatoria o está vacía, MUST impedir el arranque con un
  mensaje en español que nombre la variable.
- **FR-009**: El valor de `SUPABASE_SERVICE_KEY` y la contraseña contenida en `DATABASE_URL`
  MUST NOT aparecer en ningún mensaje, registro ni representación de texto de la configuración.

**Conexión (`connection`)**

- **FR-010**: MUST abrir el acceso a la base de datos una sola vez, al arrancar el sistema, y
  cerrarlo al apagarlo. Las peticiones reutilizan ese acceso y no abren uno propio.
- **FR-011**: MUST permitir que varias operaciones de distintos repositorios formen una sola
  unidad, que se confirma o se revierte entera (FR-005).
- **FR-012**: Si la base no responde, al arrancar o durante una operación, MUST producir el
  error del dominio de base de datos no disponible.

**Disposición de rutas (`storage_layout`)**

- **FR-013**: MUST ser el único lugar del sistema que decide la ruta de cada archivo dentro del
  bucket. Todas las rutas van bajo el código del estudio:

  | Archivo | Ruta |
  |---|---|
  | Proyección de cada ángulo | `<study_code>/projections/angle_000.npy`, `angle_045.npy`, `angle_090.npy`, `angle_135.npy` |
  | Volumen reconstruido | `<study_code>/volume.npy` |
  | Máscara de segmentación | `<study_code>/segmentation/mask.npy` |
  | Probabilidad de segmentación | `<study_code>/segmentation/probability.npy` |
  | Resumen por región | `<study_code>/segmentation/summary.json` |
  | Malla del órgano | `<study_code>/meshes/organ.glb` |
  | Malla del tumor | `<study_code>/meshes/tumor.glb` |

- **FR-014**: Las rutas MUST ser deterministas: el mismo estudio y el mismo archivo producen
  siempre la misma ruta.
- **FR-015**: MUST rechazar con el error de identificador inválido un código de estudio que no
  cumpla el formato permitido (letras, dígitos, guion y guion bajo; de 1 a 64 caracteres). Ese
  error también cubre las cadenas que contengan `..` o una barra invertida y la cadena vacía.
- **FR-016**: MUST rechazar un ángulo de proyección fuera de {0, 45, 90, 135}.
- **FR-017**: MUST NOT acceder al almacenamiento ni a la base. Solo calcula rutas.

**Almacenamiento de objetos (`object_storage`)**

- **FR-018**: MUST permitir subir un archivo a una ruta, descargarlo y comprobar si existe, en el
  bucket indicado por la configuración.
- **FR-019**: Los arreglos MUST guardarse y leerse en formato `.npy` sin objetos serializados de
  Python. Al leer, MUST rechazar un archivo que los contenga.
- **FR-020**: Todo fallo MUST producir el error del dominio de almacenamiento, con mensaje en
  español. Cuando el archivo no existe, el error debe distinguirse de un fallo de acceso.
- **FR-021**: Subir a una ruta ya ocupada MUST reemplazar el archivo anterior.

**Repositorio de pacientes (`patient_repository`)**

- **FR-022**: MUST identificar o registrar al paciente de un estudio con estas reglas:
  - Si hay DNI y ya está registrado, devuelve el paciente existente sin modificar sus datos.
  - Si hay DNI y no está registrado, crea un paciente con los datos recibidos.
  - Si no hay DNI pero hay nombre o apellido, crea un paciente nuevo con esos datos.
  - Si no hay ningún dato personal, devuelve el paciente de referencia `PAC000000`.
- **FR-023**: El nombre, el apellido y el DNI MUST ser opcionales. Cuando se registra, el DNI
  MUST tener exactamente ocho dígitos y ser único. Si no los tiene, se rechaza con un error del
  dominio.
- **FR-024**: Todo paciente nuevo MUST recibir el siguiente código consecutivo con la forma
  `PAC` más seis dígitos (`PAC000001`, `PAC000002`, …), siguiendo a `PAC000000`. El código MUST
  validarse contra `^PAC[0-9]{6}$` y ser único incluso con registros simultáneos.
- **FR-025**: El DNI, el nombre y el apellido MUST NOT aparecer en mensajes de error ni en
  registros.

**Repositorio de órganos (`organ_repository`)**

- **FR-026**: MUST devolver los órganos registrados y un órgano por su nombre (`lung` o
  `liver`). Es de solo lectura: los órganos vienen precargados por el esquema.

**Repositorio de modelos (`model_repository`)**

- **FR-027**: MUST registrar un modelo por su par (nombre, versión), con la fecha de
  entrenamiento y la descripción como datos opcionales. Si el par ya existe, MUST devolver el
  existente en lugar de crear otro.
- **FR-028**: MUST devolver un modelo por su par (nombre, versión).
- **FR-029**: La fecha de entrenamiento MUST guardarse solo cuando se conoce. Nunca se completa
  con un valor estimado.

**Repositorio de estudios (`study_repository`)**

- **FR-030**: MUST registrar un estudio nuevo con su código, su órgano y su paciente (FR-022),
  en estado `pending`.
- **FR-031**: MUST devolver un estudio por su código, o el error de estudio inexistente.
- **FR-032**: MUST devolver los estudios registrados con su estado, del más reciente al más
  antiguo.
- **FR-033**: MUST actualizar el estado del estudio (`pending`, `processing`, `completed`,
  `failed`). Al completarlo, MUST registrar el modelo de reconstrucción, el tamaño de rejilla
  y el tiempo total.
- **FR-034**: MUST rechazar un código ya registrado con un error del dominio.

**Repositorio de proyecciones (`projection_repository`)**

- **FR-035**: MUST guardar las proyecciones de un estudio con su ángulo, su ruta en el bucket y
  el nombre original del archivo (opcional).
- **FR-036**: MUST devolver las proyecciones de un estudio ordenadas por ángulo.
- **FR-037**: MUST rechazar con el error de proyección inválida un ángulo fuera de {0, 45, 90,
  135} o repetido dentro del mismo estudio.

**Repositorio de etapas (`processing_stage_repository`)**

- **FR-038**: MUST preparar las cuatro etapas de un estudio (1 preprocesamiento,
  2 reconstrucción, 3 segmentación, 4 mallas) en `waiting`. Repetir la operación MUST NOT crear
  filas duplicadas.
- **FR-039**: MUST cambiar el estado de una etapa (`running`, `completed`, `skipped`,
  `failed`). Al pasar a `running` se registra la hora de inicio, y al pasar a un estado final se
  registra la hora de fin. Cuando corresponde, MUST registrar el modelo que ejecutó la etapa.
- **FR-040**: MUST devolver las etapas de un estudio ordenadas por número.

**Repositorio de lesiones (`lesion_repository`)**

- **FR-041**: MUST guardar en una sola operación el lote de lesiones de un estudio. De cada una
  guarda la ubicación, el volumen en mm³, el diámetro máximo (opcional), la confianza y la ruta
  de la malla. Esa ruta es `<study_code>/meshes/tumor.glb` para todas las lesiones del estudio.
- **FR-042**: MUST devolver las lesiones de un estudio.
- **FR-043**: Si una lesión del lote viola una restricción (volumen no positivo, confianza fuera
  de [0, 1]), MUST rechazar el lote completo.

**Almacén de metadatos (`study_metadata_store`)**

- **FR-044**: MUST guardar los metadatos de un estudio como una sola unidad (FR-005): el
  paciente identificado o registrado, el estudio, las proyecciones (archivo en el bucket y fila
  en la base) y sus cuatro etapas en `waiting`.
- **FR-045**: MUST leer los metadatos de un estudio por su código y devolverlo completo, con su
  paciente, su órgano, su modelo, su tamaño de rejilla, sus proyecciones, sus etapas y sus
  lesiones.
- **FR-046**: MUST guardar el volumen reconstruido de un estudio en `<study_code>/volume.npy`.
  MUST comprobar que el estudio existe ANTES de subir el archivo y, si no existe, lanzar el
  error de estudio inexistente sin subir nada: el bucket es gratuito y limitado, y un volumen
  es un archivo grande que no puede quedar huérfano.

**Almacén de resultados (`result_store`)**

- **FR-047**: MUST guardar en una sola operación el resultado de la segmentación y de las
  mallas de un estudio. El resultado incluye:
  - la máscara, la probabilidad y el resumen por región en sus rutas (FR-013);
  - las mallas del órgano y del tumor;
  - las filas de lesiones.
- **FR-047a**: Cada elemento de `regions` del resumen MUST generar exactamente una fila de
  `lesion`, con esta correspondencia:

  | Clave de la región | Columna de `lesion` |
  |---|---|
  | `location` | `location` |
  | `volume_mm3` | `volume_mm3` |
  | `max_diameter_mm` | `max_diameter_mm` |
  | `confidence` (probabilidad media) | `confidence` |
  | — | `mesh_path` = `<study_code>/meshes/tumor.glb` |

  `region_id`, `confidence_min`, `confidence_max`, `voxels` y `centroid_voxel` no tienen columna
  en `lesion` y permanecen solo en `summary.json`. Si `regions` está vacía, no se crea ninguna
  fila. Como defensa, un elemento con `has_lesion` distinto de `true` MUST NOT generar fila. El
  segmentador no los envía, así que en la práctica esta comprobación no filtra nada.
- **FR-048**: Al guardar el resultado con éxito, MUST marcar las etapas 3 y 4 del estudio como
  `completed`. Si el guardado falla, las etapas MUST NOT quedar marcadas como completadas.
- **FR-049**: MUST devolver el resultado de un estudio, con sus lesiones y las rutas de sus
  archivos.
  - Si el estudio existe pero todavía no tiene resultado guardado, MUST devolver un resultado
    vacío: todas las rutas en `None` y la lista de lesiones vacía. MUST NOT lanzar error, porque
    la interfaz consulta mientras el estudio se procesa.
  - Solo MUST lanzar el error de estudio inexistente cuando el código no corresponde a ningún
    estudio.
  - Un estudio tiene resultado guardado cuando sus etapas 3 y 4 están en `completed` (FR-048).
- **FR-050**: MUST guardar `summary.json` tal como lo entrega el módulo de inferencia de
  segmentación, sin agregar, quitar ni renombrar claves. Las claves de primer nivel son
  `study_id`, `organ`, `model_name`, `model_version`, `threshold`, `mm_per_voxel`, `grid`,
  `has_lesion`, `lesion_count`, `global_confidence`, `total_volume_mm3`, `location_note` y
  `regions`. Cada elemento de `regions` trae, en este orden:

  | Clave | Tipo | Significado |
  |---|---|---|
  | `region_id` | entero | 1, 2, 3…, de mayor a menor volumen |
  | `has_lesion` | booleano | siempre `true` |
  | `location` | texto | posición geométrica, no lóbulo anatómico |
  | `volume_mm3` | decimal | vóxeles × (mm por vóxel)³ |
  | `max_diameter_mm` | decimal | mayor distancia entre dos vóxeles de la región |
  | `confidence` | decimal | probabilidad media de la región, entre 0 y 1 |
  | `confidence_min` | decimal | probabilidad mínima dentro de la región |
  | `confidence_max` | decimal | probabilidad máxima dentro de la región |
  | `voxels` | entero | cantidad de vóxeles de la región |
  | `centroid_voxel` | tres enteros | centro de masa en índices de vóxel |

  `regions` solo trae regiones con lesión. Si no hay ninguna, es `[]` y `has_lesion` del nivel
  superior es `false`.

**Fuera de alcance**

- **FR-051**: La ruta `<study_code>/meshes/lesion_<region_id>.glb` queda reservada para una
  malla por lesión. Esta funcionalidad MUST NOT generarla ni registrarla.

**Dominio**

- **FR-052**: La entidad de estudio MUST incluir su paciente, el modelo de reconstrucción usado
  y el tamaño de rejilla. La entidad de etapa MUST incluir el modelo que la ejecutó. La entidad
  de paciente MUST existir, con su código y sus datos personales opcionales.

**Calidad (constitución, Principio IV)**

- **FR-053**: Cada uno de los trece componentes MUST tener pruebas unitarias que corran sin base
  de datos, sin almacenamiento y sin red. Los componentes son la configuración, la conexión, las
  rutas, el almacenamiento de objetos, los siete repositorios y los dos almacenes. El
  comportamiento contra la base real se verifica además con pruebas de integración contra el
  Supabase de prueba.

### Key Entities *(include if feature involves data)*

- **Patient**: persona a la que pertenece un estudio. Su código interno es obligatorio. El nombre,
  el apellido y el DNI de ocho dígitos son opcionales, y el DNI es único cuando se registra.
  Existe un paciente de referencia, `PAC000000`, para estudios sin datos personales. Un paciente
  tiene muchos estudios.
- **Organ**: órgano estudiado. El alcance actual cubre dos, `lung` (tórax) y `liver` (abdomen
  superior). Un órgano tiene muchos estudios.
- **Model**: una versión de un modelo. Se identifica por el par (nombre, versión). Muchos
  estudios y etapas apuntan a la misma fila. Los pesos no se guardan en la base.
- **Study**: un órgano de un paciente procesado una vez. Tiene un código único, un estado, el
  modelo de reconstrucción usado, el tamaño de rejilla y el tiempo total.
- **Projection**: una de las cuatro radiografías de entrada de un estudio. Tiene un ángulo único
  dentro del estudio y una ruta al archivo en el bucket.
- **Processing Stage**: una de las cuatro etapas de la tubería para un estudio. Registra su
  estado, su inicio, su fin y el modelo que la ejecutó.
- **Lesion**: una región marcada como lesión por el segmentador. Registra su ubicación
  geométrica, su volumen, su diámetro máximo opcional, su confianza y la ruta de su malla.
- **Archivos de un estudio en el bucket**: cuatro proyecciones, el volumen reconstruido, la
  máscara, la probabilidad, el resumen por región, la malla del órgano y la malla del tumor.
  Todos van bajo el código del estudio. La base solo guarda rutas.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: El 100 % de los estudios guardados en las pruebas se recuperan con los mismos
  valores con que se guardaron, incluidos paciente, proyecciones, etapas, lesiones y archivos
  del bucket.
- **SC-002**: La capa de persistencia contiene 0 referencias a tablas o columnas del esquema
  anterior.
- **SC-003**: Las credenciales, el DNI, el nombre y el apellido aparecen 0 veces en los mensajes
  de error, los registros y las representaciones de configuración generados por la suite de
  pruebas.
- **SC-004**: Los 13 componentes de la capa tienen al menos una prueba unitaria, y esas pruebas
  pasan sin conexión a la red.
- **SC-005**: El 100 % de las violaciones de restricciones probadas llegan a la capa de lógica
  como errores del dominio con mensaje en español. Ninguna llega como error crudo.
- **SC-006**: En el 100 % de los arranques con configuración incompleta, el sistema no arranca y
  nombra la variable faltante.
- **SC-007**: Registrar dos estudios con el mismo DNI produce 1 paciente, no 2.
- **SC-008**: La verificación de límites entre capas
  (`tests/architecture/test_layer_boundaries.py`) pasa sin modificar la prueba.
- No se fijan metas de rendimiento: el repositorio no tiene ninguna y la constitución prohíbe
  inventarlas.

## Assumptions

- No hay datos que trasladar. La verificación del 2026-10-08 muestra 0 filas en todas las tablas
  salvo los datos iniciales (1 paciente, 2 órganos). La migración es de código, no de datos.
- Los "metadatos de un estudio" son todo lo que la base guarda sobre él: paciente, estudio,
  proyecciones, etapas y lesiones. Los binarios del bucket no forman parte de los metadatos.
- Al reutilizar un paciente por su DNI, sus datos registrados se conservan aunque lleguen otro
  nombre o apellido. Actualizar datos personales queda fuera de alcance.
- El nombre de cada etapa (`stage_name`) se deriva de su número, con los nombres en inglés del
  dominio (`preprocessing`, `reconstruction`, `segmentation`, `meshing`).
- Los valores del ejemplo de `summary.json` (umbral 0.45, 2.5 mm por vóxel, rejilla de 128) son
  ilustrativos. La persistencia no los valida ni los fija: guarda los que llegan.
- La tabla `lesion` no guarda `region_id`. Si en el futuro se implementa la malla por lesión
  (`lesion_<region_id>.glb`), habrá que relacionar cada fila con su región. Ese cambio de
  esquema queda fuera de esta funcionalidad.
- Eliminar estudios o pacientes queda fuera de alcance. El esquema ya borra en cascada
  proyecciones, etapas y lesiones si algún día se elimina un estudio.
- Se reutilizan los errores ya definidos en `domain/exceptions.py`. Si hace falta uno nuevo
  (por ejemplo, para un DNI inválido o un código duplicado), se agrega allí.
- La capa entra con la clave de servicio, que no pasa por la seguridad a nivel de fila. Definir
  políticas de seguridad a nivel de fila queda fuera de alcance.

## Open Questions

Ninguna. Todas las preguntas abiertas se respondieron en la sección Clarifications.
