# Feature Specification: Historial de estudios persistente con volumen de lesión y DNI

**Feature Branch**: `feat/persistent-study-history` (propuesta; la rama actual es `feat/rest-api-viewer`)

**Created**: 2026-10-12

**Status**: Draft

**Input**: User description: "Historial de estudios persistente con volumen de lesión y DNI"

## Contexto

Hoy el historial de la interfaz web vive en el almacenamiento del navegador: solo muestra los
estudios creados desde ese navegador, se pierde si se borran los datos del sitio y no se ve
desde otra computadora. Cada fila tiene fecha, código, órgano, estado y número de lesiones,
pero no dice de qué paciente es el estudio ni cuánto mide lo que se encontró.

La base de datos ya guarda todo lo necesario: cada estudio con su paciente (incluido el DNI
cuando se registró) y cada lesión con su volumen. Esta funcionalidad hace que el historial
salga de ahí, para que sea el mismo en cualquier navegador y no dependa de la memoria local,
y le agrega dos columnas: el DNI del paciente y el volumen de lesión del estudio.

Esto cambia una regla vigente de la funcionalidad 004 (FR-029): hasta ahora ninguna respuesta
devolvía datos personales del paciente. Esta especificación abre una única excepción, acotada
al historial (ver FR-009 a FR-012).

## Clarifications

### Session 2026-10-12

- Q: ¿Qué volumen de lesión se muestra por estudio? → A: la suma de los volúmenes de todas
  sus lesiones (carga tumoral total). Ver US2 y FR-006.
- Q: ¿Cómo se muestra el DNI? → A: completo, en todas las filas, sin enmascarar. Ver FR-010
  y Assumptions (riesgo aceptado sin autenticación).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Ver todos los estudios guardados desde cualquier navegador (Priority: P1)

El médico abre el historial y ve todos los estudios registrados en el sistema, del más
reciente al más antiguo, aunque los haya creado otra persona, desde otra computadora o antes
de borrar los datos del navegador. Cada fila muestra fecha, código, órgano, estado y número
de lesiones, como hoy. Desde una fila terminada abre el visor de ese estudio.

**Why this priority**: es el núcleo de "persistente". Sin esto, las columnas nuevas solo
aparecerían en los estudios que el navegador recuerda, y el historial seguiría siendo
distinto en cada equipo.

**Independent Test**: crear un estudio desde un navegador, abrir el historial en otro
navegador (o en una ventana privada) y comprobar que el estudio aparece con su estado actual.

**Acceptance Scenarios**:

1. **Given** tres estudios guardados en el sistema y un navegador sin datos locales,
   **When** el usuario abre el historial, **Then** ve los tres, ordenados del más reciente
   al más antiguo.
2. **Given** un estudio que pasó de `processing` a `completed`, **When** el usuario vuelve
   a abrir el historial, **Then** la fila muestra `completed` y su número de lesiones, sin
   que el usuario tenga que abrir el estudio antes.
3. **Given** un estudio borrado desde otro navegador, **When** el usuario abre el
   historial, **Then** el estudio ya no aparece.
4. **Given** una fila de un estudio `completed`, **When** el usuario la elige, **Then** se
   abre el visor de ese estudio.
5. **Given** un estudio `pending`, **When** el usuario elige su fila, **Then** puede
   retomarlo (subir proyecciones o procesarlo), como hoy.
6. **Given** el sistema sin estudios, **When** el usuario abre el historial, **Then** ve un
   mensaje de historial vacío con el acceso a "Nuevo estudio".

---

### User Story 2 - Ver el volumen de lesión de cada estudio (Priority: P1)

En cada fila de un estudio terminado, el médico ve el volumen de lesión del estudio: la suma
de los volúmenes de todas sus lesiones (carga tumoral total), con el mismo formato que el visor (FR-007). Así
compara de un vistazo estudios del mismo paciente o de pacientes distintos sin abrir el visor
de cada uno.

**Why this priority**: es el dato clínico que el usuario pidió de forma explícita, y se
calcula con información que ya está guardada. Es independiente del DNI: puede entregarse
sola.

**Independent Test**: procesar un estudio de prueba con lesiones conocidas y comprobar que la
fila del historial muestra el volumen que corresponde a las lesiones guardadas, con el mismo
redondeo que el visor.

**Acceptance Scenarios**:

1. **Given** un estudio `completed` con lesiones, **When** se abre el historial, **Then**
   su fila muestra la suma de los volúmenes de sus lesiones con el mismo formato y el mismo número de
   decimales que el visor muestra para cada lesión.
2. **Given** un estudio `completed` sin lesiones, **When** se abre el historial, **Then**
   la columna de volumen muestra "0" o "sin lesiones", nunca un guion que se confunda con
   "dato faltante".
3. **Given** un estudio `pending`, `processing` o `failed`, **When** se abre el historial,
   **Then** la columna de volumen muestra un guion: no hay resultado.
4. **Given** un estudio cuyo volumen se muestra en el historial, **When** el usuario abre
   el visor de ese estudio, **Then** el volumen del historial coincide con la suma de los
   volúmenes de las lesiones que muestra el visor, al redondeo mostrado.

---

### User Story 3 - Identificar al paciente por su DNI y encontrar sus estudios (Priority: P2)

El médico ve en cada fila el DNI del paciente del estudio y puede escribir un DNI para ver
solo los estudios de esa persona. Así sigue la evolución de un paciente a lo largo del tiempo
(por ejemplo, el volumen de lesión de un estudio a otro).

**Why this priority**: da el contexto de "de quién es" y habilita el seguimiento por
paciente, pero implica mostrar un dato personal y abrir una excepción a una regla vigente
(ver FR-009 a FR-013). Las historias 1 y 2 tienen valor sin esta.

**Independent Test**: crear dos estudios con el mismo DNI y uno con otro DNI; filtrar por el
primer DNI y comprobar que aparecen exactamente los dos primeros.

**Acceptance Scenarios**:

1. **Given** un estudio cuyo paciente se registró con DNI, **When** se abre el historial,
   **Then** la fila muestra el DNI según la regla de FR-010.
2. **Given** un estudio cuyo paciente se registró sin DNI, **When** se abre el historial,
   **Then** la columna de DNI muestra "sin DNI" (o un guion), y la fila se ve igual que las
   demás.
3. **Given** varios estudios de distintos pacientes, **When** el usuario escribe un DNI de
   ocho dígitos en el filtro, **Then** el historial muestra solo los estudios de ese DNI,
   del más reciente al más antiguo.
4. **Given** un DNI que no tiene estudios, **When** el usuario filtra por él, **Then** ve
   "No hay estudios para ese DNI", sin error.
5. **Given** un valor que no son ocho dígitos, **When** el usuario intenta filtrar, **Then**
   la interfaz le indica que el DNI tiene exactamente ocho dígitos y no consulta al sistema.
6. **Given** el filtro aplicado, **When** el usuario lo limpia, **Then** vuelve a ver todos
   los estudios.

---

### Edge Cases

- **Estudios anteriores a esta funcionalidad**: aparecen en el historial, porque ya están en
  la base. Los que se procesaron sin paciente propio (paciente de referencia) se muestran
  "sin DNI".
- **Historial local existente**: las entradas que el navegador guardó con la versión
  anterior dejan de ser la fuente del historial. Si un código del historial local no existe
  en el sistema, no se muestra (ya no hay "estudio borrado" pendiente de quitar).
- **El sistema no responde**: el historial muestra un mensaje de error con opción de
  reintentar, y no muestra una lista vieja como si fuera actual.
- **Muchos estudios**: con más estudios de los que caben en una página (ver FR-005), el
  usuario puede ver los siguientes; el orden se mantiene entre páginas.
- **Estudio borrado mientras el historial está abierto**: al elegir su fila, el usuario ve
  "Este estudio ya no existe" y la fila desaparece al recargar.
- **Lesión con volumen muy pequeño**: por debajo de 1 cm³ el volumen se muestra en mm³, como
  en el visor, así que nunca aparece como "0 cm³" ni se confunde con "sin lesiones".
- **Estudio `failed` después de guardar lesiones parciales**: la columna de volumen muestra
  un guion; solo un estudio `completed` tiene volumen.
- **Dos pacientes con el mismo DNI**: no puede ocurrir; el sistema ya garantiza que un DNI
  pertenece a un solo paciente.

## Requirements *(mandatory)*

### Functional Requirements

**Historial persistente**

- **FR-001**: El sistema MUST ofrecer una consulta que devuelve los estudios guardados, del
  más reciente al más antiguo, a partir de la información persistida, sin depender de nada
  guardado en el navegador.
- **FR-002**: Cada elemento del historial MUST incluir: código del estudio, órgano, estado,
  fecha de creación, número de lesiones y volumen de lesión (FR-006), y el DNI según FR-010.
- **FR-003**: El estado de cada estudio en el historial MUST ser el estado actual guardado,
  no una copia anterior.
- **FR-004**: La página de historial MUST obtener su lista de esa consulta. El almacenamiento
  del navegador MUST NOT ser la fuente de las filas mostradas.
- **FR-005**: La consulta MUST devolver los estudios por páginas de tamaño acotado (50 por
  defecto) e indicar si hay más; la página MUST permitir ver las siguientes.
- **FR-005a**: Elegir una fila MUST conservar el comportamiento actual: abrir el visor de un
  estudio `completed` y retomar uno `pending`.

**Volumen de lesión**

- **FR-006**: Para cada estudio `completed`, el historial MUST mostrar el volumen de lesión
  calculado a partir de las lesiones guardadas del estudio,
  como la suma de los volúmenes de todas sus lesiones (carga tumoral total). El volumen de
  cada lesión por separado sigue viéndose en el visor.
- **FR-007**: El volumen MUST mostrarse con el mismo formato que usa el visor para el volumen
  de cada lesión: en cm³ desde 1 cm³, en mm³ por debajo, con el mismo redondeo y separador
  decimal (ajustado en el plan, research.md R5: muchas lesiones miden menos de 1 cm³).
- **FR-008**: Un estudio que no está `completed` MUST NOT mostrar volumen. Un estudio
  `completed` sin lesiones MUST mostrar un valor que diga "sin lesiones" o 0, distinto del
  guion de "sin resultado".

**DNI y datos personales**

- **FR-009**: El DNI MUST ser el único dato personal que devuelve la consulta del historial.
  Nombre y apellido MUST NOT salir en ella.
- **FR-010**: El historial MUST mostrar el DNI completo (los ocho dígitos, sin enmascarar)
  del paciente de cada estudio, en todas las filas. Un paciente sin DNI MUST mostrarse como
  "sin DNI".
- **FR-011**: El usuario MUST poder filtrar el historial por un DNI de exactamente ocho
  dígitos. Un valor con otro formato MUST rechazarse con un mensaje y sin consultar.
- **FR-012**: El DNI MUST NOT aparecer en registros del sistema, mensajes de error, la
  dirección de la página (URL) ni el almacenamiento del navegador. Las demás respuestas
  (estado, resultado, creación) MUST seguir sin devolver datos personales, como exige FR-029
  de la funcionalidad 004.
- **FR-013**: La excepción a FR-029 de la funcionalidad 004 MUST quedar documentada en el
  contrato de la API y en la especificación 004, para que no se lea como una contradicción.

**Errores y pruebas**

- **FR-014**: Si la consulta del historial falla, la página MUST mostrar un mensaje en
  español con opción de reintentar, y MUST NOT mostrar filas de una consulta anterior como
  si fueran actuales.
- **FR-015**: MUST existir pruebas unitarias de la consulta del historial con un servicio
  falso: orden, paginación, filtro por DNI, DNI ausente, volumen de un estudio con lesiones,
  sin lesiones y no terminado, y ausencia de nombre y apellido en la respuesta.
- **FR-016**: MUST existir una prueba que verifica que un DNI con formato inválido en el
  filtro devuelve un error de validación cuyo texto no contiene el valor enviado.
- **FR-017**: MUST existir una prueba de integración contra la base de prueba que crea
  estudios con y sin DNI, guarda lesiones con volumen conocido y comprueba los valores que
  devuelve el historial.

### Key Entities *(include if feature involves data)*

- **Elemento del historial**: vista de un estudio pensada para la lista. Código, órgano,
  estado, fecha de creación, número de lesiones, volumen de lesión y DNI del paciente. No es
  una entidad nueva en la base: se arma con lo que ya guardan el estudio, su paciente y sus
  lesiones.
- **Estudio** (existente): un órgano de un paciente procesado una vez; aporta código,
  órgano, estado y fecha.
- **Paciente** (existente): aporta el DNI, opcional y único cuando se registra.
- **Lesión** (existente): región detectada en un estudio; aporta su volumen en mm³.
- **Página del historial**: un tramo de elementos en orden y la indicación de si hay más.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un estudio creado en un navegador aparece en el historial de cualquier otro
  navegador en el 100 % de los casos de prueba, sin pasos adicionales.
- **SC-002**: Con 500 estudios guardados, la primera página del historial se ve completa en
  menos de 2 segundos en el entorno de demostración.
- **SC-003**: En el 100 % de los estudios de prueba con lesiones conocidas, el volumen del
  historial coincide con la suma de los volúmenes de las lesiones del visor, al redondeo
  mostrado.
- **SC-004**: Filtrar por un DNI muestra exactamente los estudios de ese paciente en el
  100 % de los casos de prueba (ni uno de más, ni uno de menos).
- **SC-005**: En el 100 % de las respuestas, registros y mensajes de error revisados por las
  pruebas, no aparecen nombre ni apellido del paciente, y el DNI solo aparece en la consulta
  del historial.
- **SC-006**: Un médico encuentra todos los estudios de un paciente a partir de su DNI en
  menos de 15 segundos desde que abre el historial.

## Assumptions

- **Usuarios**: el sistema sigue sin autenticación ni roles (fuera de alcance en la 004).
  Quien puede abrir la interfaz puede ver el historial completo, con el DNI completo de cada
  paciente (FR-010). Es un riesgo aceptado de forma explícita para el entorno de
  demostración. Si el sistema se expone fuera de ese entorno, hay que revisar FR-010 junto
  con la autenticación.
- **Alcance del historial**: muestra todos los estudios del sistema, no solo los creados
  desde el navegador actual.
- **DNI**: se mantiene el formato vigente, ocho dígitos (DNI peruano). Sigue siendo opcional
  al crear el estudio; esta funcionalidad no lo vuelve obligatorio.
- **Volumen**: se calcula al consultar a partir de los volúmenes de lesión ya guardados en
  mm³; no se guarda un total aparte. 1 cm³ = 1000 mm³.
- **Borrado**: un estudio borrado desaparece del historial; no hay papelera ni registro de
  estudios borrados.
- **Historial local**: la clave del navegador que guardaba el historial anterior puede
  quedar sin uso; limpiarla o no se decide en el plan.
- **Mensajes**: van en español; rutas, campos y nombres de código, en inglés (Principio III).

## Out of Scope

- Autenticación, usuarios, permisos y registro de quién consultó qué.
- Mostrar nombre y apellido del paciente en el historial.
- Búsqueda por nombre, por código parcial, por rango de fechas o por órgano.
- Gráficos de evolución del volumen de un paciente en el tiempo.
- Exportar el historial (CSV, PDF).
- Editar los datos del paciente de un estudio ya creado.
- Aceptar documentos que no sean DNI de ocho dígitos (pasaporte, carné de extranjería).
