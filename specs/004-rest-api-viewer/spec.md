# Feature Specification: Capa de API REST y visor 3D

**Feature Branch**: `feat/rest-api-viewer` (propuesta; la rama actual es `feat/services-pipeline`)

**Created**: 2026-10-09

**Status**: Draft

**Input**: User description: "Capa de API REST (Layer 1). FastAPI con APIRouter por recurso
(studies, projections, results). Endpoints: POST /studies, POST /studies/{id}/projections
(sube 4 .npy), POST /studies/{id}/process (lanza pipeline en background task),
GET /studies/{id}/status, GET /studies/{id}/result (devuelve URLs de mallas .glb y volumen),
DELETE /studies/{id}. Schemas Pydantic. DI con Depends(get_study_service) desde app.state.
Sin importar persistence ni torch directamente. Visor 3D en GET /viewer/{id}: HTML con
Three.js que carga las mallas .glb del resultado y las muestra interactivo (organo
semitransparente, tumores opacos por lesion). La tabla lesion usa organ como texto, sin
region_id."

## Clarifications

### Session 2026-10-09

Esta especificación toma al pie de la letra las dos frases de la descripción sobre las
lesiones. Una lectura conservadora (malla única del tumor, sin cambios en la base) se
descartó.

- Q: ¿"Tumores opacos por lesión" pide una malla por lesión? → A: Sí. La etapa de mallas
  genera un `.glb` por cada lesión, y el visor dibuja cada una opaca y en su propio color
  dentro del órgano semitransparente. El color de cada malla coincide con el de su fila en la
  lista de lesiones.
- Q: ¿Cómo se enlaza cada lesión con su malla sin `region_id`? → A: Por la columna
  `mesh_path` que la tabla `lesion` ya tiene. Hoy todas las filas apuntan a `tumor.glb`; con
  esta funcionalidad, cada fila apunta a su propio archivo. `region_id` sigue solo en
  `summary.json` y no llega a la base ni a la API.
- Q: ¿"La tabla lesion usa organ como texto" pide una columna en la base? → A: Sí. La tabla
  `lesion` gana la columna `organ` de texto (`lung` o `liver`), con el mismo control de
  valores que `organ.name`. No es una clave foránea.

## User Scenarios & Testing *(mandatory)*

El actor es quien carga un estudio desde el navegador o desde un cliente HTTP: crea el
estudio, sube las cuatro radiografías, lo manda a procesar, consulta el avance y abre el
resultado en el visor 3D. La capa de lógica ya existe (`specs/002-services-pipeline/`) y
procesa un estudio de punta a punta, pero hoy nada la expone: los routers de `api/` son
esqueletos que lanzan `NotImplementedError` y el visor es una página vacía.

La interfaz HTTP es el producto de esta funcionalidad. Por eso las rutas y los códigos de
respuesta aparecen en los requisitos: son el contrato que ve el usuario, no un detalle
interno.

### User Story 1 - Cargar y procesar un estudio por HTTP (Priority: P1)

Quien usa el sistema:

1. crea un estudio con su código, su órgano y, si quiere, los datos del paciente;
2. sube las cuatro proyecciones `.npy`, una por cada ángulo (0, 45, 90 y 135 grados);
3. pide procesarlo. La respuesta llega enseguida, sin esperar a que termine la tubería;
4. consulta el estado hasta que el estudio queda en `completed` o en `failed`.

**Why this priority**: sin esto el sistema no se puede usar desde fuera. Es el mínimo que
demuestra que la tubería funciona a través de la red. Si solo se entrega esta historia, ya
se puede procesar un estudio y ver su avance etapa por etapa.

**Independent Test**: con un servicio falso inyectado en lugar del real (sin base, sin
modelos), recorrer las cuatro llamadas en orden y comprobar los códigos de respuesta, la
forma de cada respuesta y que el procesamiento se lanzó una sola vez y en segundo plano.

**Acceptance Scenarios**:

1. **Given** un código de estudio libre y el órgano `lung`, **When** se crea el estudio,
   **Then** la respuesta confirma la creación con el código, el órgano y el estado
   `pending`.
2. **Given** un estudio `pending` sin proyecciones, **When** se suben cuatro `.npy` válidos,
   uno por ángulo, **Then** la respuesta confirma los cuatro ángulos recibidos.
3. **Given** un estudio `pending` con sus cuatro proyecciones, **When** se pide procesarlo,
   **Then** la respuesta llega sin esperar a la tubería, confirma que el procesamiento
   empezó y el estudio pasa a `processing`.
4. **Given** un estudio en proceso, **When** se consulta su estado, **Then** la respuesta
   trae el estado del estudio y el de cada una de las cuatro etapas (`waiting`, `running`,
   `completed`, `skipped` o `failed`).
5. **Given** un estudio procesado, **When** se consulta su estado, **Then** aparece
   `completed` con el tiempo total.

---

### User Story 2 - Rechazar pedidos inválidos con mensajes claros (Priority: P1)

Si el pedido es inválido o llega en un momento en que no corresponde, la respuesta dice qué
pasó, con un código HTTP que lo distingue, y nunca muestra datos del paciente.

**Why this priority**: va con la historia 1. Un cliente que no puede distinguir "no existe"
de "todavía no está listo" o de "subiste mal un archivo" no puede usar el sistema.

**Independent Test**: con el servicio falso configurado para lanzar cada error del dominio,
comprobar el código HTTP y el mensaje de cada caso, y que ningún cuerpo de respuesta
contenga nombre, apellido ni DNI.

**Acceptance Scenarios**:

1. **Given** un código de estudio que ya existe, **When** se crea otro con el mismo código,
   **Then** se rechaza con conflicto y el primero no cambia.
2. **Given** un código con caracteres no permitidos o un órgano fuera del alcance, **When**
   se crea el estudio, **Then** se rechaza como entrada inválida y no se crea nada.
3. **Given** el órgano `liver`, **When** se crea el estudio, **Then** se rechaza con un
   mensaje que dice que no hay modelo de hígado y no se crea nada.
4. **Given** una subida con tres archivos, un ángulo repetido, un PNG, un `.npy` de forma
   distinta de 128 × 128 o con valores no finitos, **When** se suben las proyecciones,
   **Then** se rechaza como entrada inválida con un mensaje que nombra el ángulo afectado, y
   el estudio queda sin proyecciones.
5. **Given** un estudio sin proyecciones, o uno que ya está en `processing`, `completed` o
   `failed`, **When** se pide procesarlo, **Then** se rechaza con conflicto y el estudio no
   cambia.
6. **Given** un código inexistente, **When** se llama a cualquier ruta del estudio, **Then**
   se responde "no encontrado".

---

### User Story 3 - Ver el resultado en 3D (Priority: P2)

Con un estudio `completed`, quien usa el sistema abre el visor del estudio en el navegador
y ve el órgano semitransparente con cada lesión dentro como una malla opaca de su propio
color. Puede rotar, acercar y desplazar la escena con el ratón, y ve al lado la lista de
lesiones detectadas, cada una con el color de su malla.

**Why this priority**: es el valor visible del sistema, pero depende de la historia 1. Sin
el visor, el resultado ya se puede descargar y abrir con cualquier programa de mallas.

**Independent Test**: con un estudio de ejemplo terminado (con los dobles de la capa de
lógica), abrir el visor en un navegador y comprobar que se ven la malla del órgano y una malla por
lesión, que el órgano deja ver las lesiones a través y que la lista muestra una fila por
lesión con el color de su malla.

**Acceptance Scenarios**:

1. **Given** un estudio `completed`, **When** se pide su resultado, **Then** la respuesta
   trae las direcciones para descargar la malla del órgano y el volumen reconstruido, más la
   lista de lesiones, cada una con la dirección de descarga de su propia malla.
2. **Given** un estudio `completed`, **When** se abre su visor, **Then** se ve la malla del
   órgano semitransparente y, dentro, una malla opaca por cada lesión, cada una en un color
   distinto.
3. **Given** el visor abierto, **When** se arrastra, se usa la rueda o se arrastra con el
   botón derecho, **Then** la escena rota, se acerca o se desplaza.
4. **Given** el visor abierto, **When** se mira la lista de lesiones, **Then** cada fila
   muestra el color de su malla, el órgano como texto (`lung`), la ubicación, el volumen
   en mm³, el diámetro máximo en mm y la confianza, sin ningún identificador de región.
5. **Given** un estudio `completed` sin lesiones, **When** se abre su visor, **Then** se ve
   solo el órgano y un aviso de que no se detectaron lesiones.
6. **Given** un estudio que no está `completed`, **When** se abre su visor, **Then** la
   página muestra el estado actual del estudio en lugar de una escena vacía.
7. **Given** el visor abierto, **When** se elige una fila de la lista, **Then** su malla
   queda resaltada en la escena.
8. **Given** un estudio procesado con dos lesiones, **When** se consulta la tabla `lesion`,
   **Then** hay dos filas, cada una con `organ` = `lung` y un `mesh_path` distinto que
   apunta a un `.glb` existente.

---

### User Story 4 - Borrar un estudio (Priority: P3)

Quien usa el sistema borra un estudio de prueba o mal cargado, con todos sus archivos.

**Why this priority**: la capa de lógica ya lo resuelve; aquí solo se expone. Es necesario
para limpiar, pero no bloquea el uso principal.

**Independent Test**: con el servicio falso, borrar un estudio y comprobar la respuesta;
borrar uno en `processing` y comprobar el conflicto.

**Acceptance Scenarios**:

1. **Given** un estudio `pending`, `completed` o `failed`, **When** se borra, **Then** la
   respuesta confirma el borrado sin cuerpo y pedirlo después responde "no encontrado".
2. **Given** un estudio en `processing`, **When** se pide borrarlo, **Then** se rechaza con
   conflicto y el estudio sigue intacto.

---

### Edge Cases

- **Dos pedidos de procesar el mismo estudio a la vez**: solo uno lanza la tubería; el otro
  recibe conflicto.
- **Una segunda subida de proyecciones**: si el estudio ya tiene sus cuatro proyecciones, se
  rechaza con conflicto. Para corregirlas, se borra el estudio y se crea de nuevo.
- **Subida con nombres de archivo que no indican el ángulo**: el ángulo de cada archivo lo
  dice el pedido, no el nombre del archivo.
- **Archivo demasiado grande**: se rechaza antes de leerlo entero, con un mensaje que dice el
  tamaño máximo. Un `.npy` de 128 × 128 en float32 pesa unos 64 KB.
- **La tubería falla en segundo plano**: el pedido de procesar ya respondió. El fallo se ve
  en el estado: el estudio en `failed`, la etapa que falló en `failed` y las siguientes en
  `skipped`. El detalle técnico va al registro del servidor, no a la respuesta.
- **El servidor se reinicia con un estudio en `processing`**: la tarea en segundo plano
  murió con el proceso. Al arrancar, ese estudio pasa a `failed` para que no quede colgado y
  se pueda borrar.
- **Pedir el resultado de un estudio que no está `completed`**: conflicto, con un mensaje que
  dice el estado actual. No se devuelven direcciones vacías.
- **Pedir un archivo de un estudio borrado entre la consulta del resultado y la descarga**:
  "no encontrado".
- **Modelo no disponible al procesar** (pesos ausentes al arrancar): el pedido de procesar
  se rechaza como servicio no disponible y el estudio sigue en `pending`.
- **Estudio sin lesiones**: no hay filas de `lesion` ni mallas por lesión. El visor muestra
  solo el órgano y el aviso de la historia 3.
- **Lesión muy pequeña** (pocos vóxeles): su malla se genera igual, aunque tenga pocos
  triángulos. Si el algoritmo de mallas no puede formar ninguna superficie, se guarda un
  `.glb` válido sin geometría y la fila aparece en la lista; el visor no falla.
- **Muchas lesiones**: el visor asigna colores distinguibles a las primeras siete y repite la
  paleta a partir de la octava; la lista sigue mostrando el color de cada una.
- **Navegador sin soporte 3D**: el visor muestra un mensaje que lo dice, con las direcciones
  de descarga de las mallas.

## Requirements *(mandatory)*

### Functional Requirements

**Organización de la capa**

- **FR-001**: La capa de presentación MUST organizarse en un router por recurso: estudios,
  proyecciones, resultados y visor. El punto de entrada solo los monta. Los routers
  esqueleto actuales de reconstrucción y segmentación se reemplazan; sus rutas no se
  conservan.
- **FR-002**: Cada petición y cada respuesta MUST tener un esquema declarado, para que la
  entrada se valide y la documentación interactiva del servicio se genere sola.
- **FR-003**: Los routers MUST recibir el servicio de estudios por inyección de dependencias,
  leído del estado de la aplicación que arma el arranque. No lo construyen.
- **FR-004**: `api/` MUST NOT importar `persistence`, `psycopg`, `supabase` ni `torch`. Las
  pruebas de arquitectura existentes MUST seguir en verde sin modificarse.

**Estudios**

- **FR-005**: `POST /studies` MUST crear un estudio `pending` a partir de su código, su órgano
  y los datos opcionales del paciente (nombre, apellido, DNI). Responde "creado" con el
  código, el órgano y el estado.
- **FR-006**: La creación MUST rechazar un código repetido (conflicto), un código fuera del
  formato permitido, un órgano fuera del alcance o datos del paciente inválidos (entrada
  inválida), y un órgano sin modelo disponible (servicio no disponible). En ningún caso se
  crea el estudio.
- **FR-007**: `GET /studies/{study_code}/status` MUST devolver el código, el órgano, el estado
  del estudio, el tiempo total si terminó, y por cada una de las cuatro etapas su número, su
  nombre, su estado, su inicio y su fin.
- **FR-008**: `DELETE /studies/{study_code}` MUST borrar el estudio con todos sus archivos y
  responder sin cuerpo. Un estudio en `processing` MUST rechazarse con conflicto.

**Proyecciones**

- **FR-009**: `POST /studies/{study_code}/projections` MUST recibir en un solo pedido
  exactamente cuatro archivos `.npy`, cada uno asociado a un ángulo de 0, 45, 90 y 135
  grados. Se aplican las validaciones de la capa de lógica (FR-010 y FR-011 de 002): forma
  128 × 128, valores finitos, sin objetos serializados, sin reescalar.
- **FR-010**: Si alguna proyección es inválida, MUST rechazarse la subida entera con un
  mensaje que nombra el ángulo, y el estudio MUST quedar sin proyecciones guardadas.
- **FR-011**: Solo se MUST aceptar la subida en un estudio `pending` que todavía no tiene
  proyecciones. En cualquier otro caso, conflicto.
- **FR-012**: Cada archivo subido MUST tener un tamaño máximo, fijado en la configuración, y
  rechazarse si lo supera sin leerlo entero.

**Procesamiento**

- **FR-013**: `POST /studies/{study_code}/process` MUST lanzar la tubería en segundo plano y
  responder "aceptado" sin esperar a que termine, con el estudio ya en `processing`.
- **FR-014**: Procesar MUST rechazarse con conflicto si el estudio no tiene sus cuatro
  proyecciones o no está `pending`. Si dos pedidos llegan a la vez, solo uno lanza la tubería.
- **FR-015**: Si falta el modelo del órgano, procesar MUST rechazarse como servicio no
  disponible antes de lanzar nada, y el estudio MUST seguir en `pending`.
- **FR-016**: Un fallo de la tubería en segundo plano MUST quedar registrado en el estado del
  estudio y de sus etapas, y en el registro del servidor. No se pierde en silencio.
- **FR-017**: Al arrancar, todo estudio que haya quedado en `processing` MUST pasar a
  `failed`, porque ninguna tarea lo está procesando.

**Resultados**

- **FR-018**: `GET /studies/{study_code}/result` MUST devolver, para un estudio `completed`:
  - la dirección de descarga de la malla del órgano (`.glb`);
  - la dirección de descarga de la malla del tumor completo (`.glb`), que se sigue generando
    como en 002;
  - la dirección de descarga del volumen reconstruido;
  - la lista de lesiones (FR-021).
- **FR-019**: Si el estudio no está `completed`, el resultado MUST rechazarse con conflicto y
  un mensaje que dice el estado actual.
- **FR-020**: Las direcciones de descarga MUST apuntar a rutas del propio servicio, que
  entregan el archivo pidiéndolo a la capa de lógica. El navegador nunca recibe la dirección
  del bucket ni una credencial. Las mallas se entregan con el tipo de contenido de `.glb`.
- **FR-021**: Cada lesión de la respuesta MUST traer el órgano como texto (el nombre del
  órgano del estudio, por ejemplo `lung`), la ubicación, el volumen en mm³, el diámetro
  máximo en mm (puede faltar), la confianza y la dirección de descarga de su propia malla
  `.glb`. MUST NOT traer `region_id` ni ningún identificador interno de la base. El órgano
  sale de la columna `organ` de la tabla `lesion` (FR-021b).

**Cambios en las capas inferiores por la malla por lesión**

- **FR-021a**: La etapa de mallas MUST generar, además de las mallas del órgano y del tumor
  de 002, un `.glb` por cada lesión, a partir de la región de la máscara que le corresponde,
  con las mismas reglas (marching cubes, milímetros, 2,5 mm por vóxel).
- **FR-021b**: La tabla `lesion` MUST ganar la columna `organ`, de texto y no nula, con el
  mismo control de valores que `organ.name` (`lung` o `liver`). Se llena con el órgano del
  estudio al guardar el resultado. La migración llena las filas que ya existan con el órgano
  de su estudio.
- **FR-021c**: El `mesh_path` de cada fila de `lesion` MUST apuntar a la malla de esa lesión,
  no a `tumor.glb`. Es el único enlace entre la fila y su malla: `region_id` MUST NOT llegar a
  la base. Esto reemplaza la regla de 001 que hacía apuntar todas las filas a `tumor.glb`.
- **FR-021d**: El borrado de un estudio (FR-015 de 002) MUST borrar también las mallas por
  lesión. El diccionario de datos y el contrato de la persistencia se actualizan en el mismo
  cambio.

**Visor 3D**

- **FR-022**: `GET /viewer/{study_code}` MUST devolver una página que carga la malla del
  órgano y la malla de cada lesión a través de las direcciones de FR-018 y FR-021, y las
  muestra en una escena 3D.
- **FR-023**: La malla del órgano MUST verse semitransparente y cada malla de lesión opaca,
  cada una en un color distinto del órgano y de las demás lesiones, de modo que las lesiones
  se vean a través del órgano.
- **FR-023a**: Cada fila de la lista de lesiones MUST mostrar el color de su malla. Elegir una
  fila MUST resaltar su malla en la escena.
- **FR-024**: La escena MUST permitir rotar, acercar y desplazar con el ratón, y volver a la
  vista inicial. La vista inicial MUST encuadrar el órgano completo.
- **FR-025**: La página MUST mostrar junto a la escena la lista de lesiones con los campos de
  FR-021 (salvo la dirección de descarga, que se ofrece como enlace), o un aviso si no hay
  lesiones.
- **FR-026**: Si el estudio no está `completed`, la página MUST mostrar su estado. Si el
  estudio no existe, MUST mostrar que no existe. Si el navegador no puede dibujar 3D, MUST
  decirlo y ofrecer las descargas.
- **FR-027**: El código del visor MUST seguir la convención de nombres del proyecto
  (snake_case también en JavaScript) y usar solo bibliotecas gratuitas.

**Errores y datos personales**

- **FR-028**: Cada error del dominio MUST traducirse a un código HTTP en un solo lugar:
  - "no encontrado": estudio inexistente;
  - entrada inválida: código, órgano, paciente o proyección inválidos;
  - conflicto: estudio duplicado, estudio en un estado que no admite la operación;
  - servicio no disponible: modelo o base no disponibles;
  - error interno: cualquier otro.
  Un error que no es del dominio MUST responder error interno con un mensaje genérico, sin
  la traza.
- **FR-029**: Ninguna respuesta de error ni registro de la capa MUST contener nombre,
  apellido ni DNI del paciente. Las respuestas de estado y de resultado MUST NOT devolver esos
  datos; a lo sumo, el código de paciente.

**Pruebas**

- **FR-030**: Cada ruta MUST tener pruebas unitarias que sustituyen el servicio por uno falso
  (sin base, sin modelos, sin PyTorch): camino feliz, cada error mapeado y la forma de la
  respuesta.
- **FR-031**: MUST existir una prueba de punta a punta que crea, sube, procesa, consulta,
  pide el resultado, descarga las mallas y borra un estudio contra la aplicación levantada
  con los dobles de la capa de lógica.
- **FR-032**: MUST existir una prueba que verifica que el procesamiento en segundo plano no
  bloquea las consultas de estado de otros estudios.
- **FR-033**: MUST existir pruebas de la malla por lesión: unitarias de la etapa de mallas con
  una máscara de dos regiones (dos `.glb` distintos, cada uno solo con su región), y de
  integración de la persistencia (cada fila con su `organ` y su propio `mesh_path`, y el
  borrado que no deja ninguna malla huérfana).

### Key Entities

- **Estudio (vista HTTP)**: código, órgano, estado, tiempo total, código de paciente. Sin
  datos personales.
- **Estado de etapa**: número, nombre, estado, inicio y fin de una de las cuatro etapas.
- **Proyección subida**: un archivo `.npy` asociado a un ángulo.
- **Resultado (vista HTTP)**: direcciones de descarga de la malla del órgano, la malla del
  tumor completo y el volumen, más la lista de lesiones.
- **Lesión (vista HTTP)**: órgano como texto, ubicación, volumen en mm³, diámetro máximo en
  mm, confianza y dirección de descarga de su malla. Sin `region_id`.
- **Lesión (tabla `lesion`)**: gana la columna `organ` de texto. Su `mesh_path` apunta a su
  propia malla. Sigue sin `region_id`.
- **Malla de lesión**: un `.glb` por lesión, generado desde su región de la máscara.
- **Visor**: página de un estudio que muestra sus mallas y su lista de lesiones.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Un estudio de ejemplo recorre crear, subir, procesar, consultar hasta
  `completed`, pedir el resultado y abrir el visor sin intervención manual, en el 100 % de
  las corridas de la prueba de punta a punta.
- **SC-002**: El pedido de procesar responde en menos de 1 segundo, sin importar cuánto
  tarde la tubería.
- **SC-003**: Mientras un estudio se procesa, las consultas de estado de cualquier estudio
  responden en menos de 1 segundo.
- **SC-004**: En el visor, la malla del órgano y las de todas las lesiones de un estudio de
  ejemplo se ven en menos de 5 segundos desde que se abre la página, en la misma red que el
  servicio.
- **SC-004a**: En el 100 % de los estudios de prueba, cada lesión de la lista tiene exactamente
  una malla en la escena, con el mismo color en la lista y en la escena.
- **SC-005**: El 100 % de los errores del dominio provocados en las pruebas responde con su
  código HTTP esperado, y ninguno contiene datos personales del paciente.
- **SC-006**: La suite unitaria de la capa de presentación corre completa en menos de 10
  segundos en una laptop sin GPU.
- **SC-007**: El análisis de estilo, la verificación de nombres y las pruebas de
  arquitectura pasan sin errores, y la cobertura de `api/` es de al menos 80 %.

## Assumptions

- **Cambios en las capas inferiores**: el flujo en tres pasos (crear, subir, procesar) no
  existe hoy. `StudyService.process_study` recibe todo junto y la persistencia registra el
  estudio y sus proyecciones en una sola operación. Esta funcionalidad agrega a la capa de
  lógica (y a la persistencia, si hace falta) las operaciones de crear un estudio sin
  proyecciones, guardar sus proyecciones, procesar un estudio ya registrado, entregar los
  archivos del resultado y marcar como `failed` los estudios colgados al arrancar. El
  diseño se decide en el plan.
- **Malla por lesión**: cambia decisiones de 001 y 002, que la dejaban fuera de alcance y
  reservaban la ruta `lesion_<region_id>.glb`. El nombre del archivo de cada malla se decide
  en el plan; como el enlace con la fila es `mesh_path`, el nombre no necesita `region_id`.
  La región de cada lesión se toma del resumen dentro de la capa de lógica, antes de guardar,
  así que `region_id` no hace falta después.
- **`tumor.glb`**: se sigue generando y ofreciendo para descargar, para no romper lo que ya
  fija 002. El visor no lo dibuja: dibuja las mallas por lesión.
- **Columna `organ` en `lesion`**: repite el órgano del estudio. Se acepta la repetición
  porque la descripción lo pide así; el control de valores evita que se desalinee de los
  órganos permitidos.
- **Código del estudio**: lo elige quien crea el estudio, con el formato que ya valida la
  persistencia. El sistema no lo genera.
- **Ejecución en segundo plano**: la tubería corre dentro del mismo proceso del servicio, en
  una tarea posterior a la respuesta. No hay cola externa ni reintentos.
- **Autenticación**: fuera de alcance. El servicio se usa en un entorno local o de
  demostración. Cualquiera que llegue al servicio puede crear, ver y borrar estudios.
- **Descargas**: el servicio entrega los archivos él mismo (FR-020) en lugar de dar
  direcciones firmadas del bucket. Así el bucket sigue privado y ninguna dirección vence a
  mitad de la carga del visor.
- **Volumen**: se ofrece para descargar en el formato en que se guarda (`.npy`). El visor no
  lo dibuja.
- **Estado de las etapas**: la consulta usa lo que ya registra la persistencia (FR-007 de
  002). No hay porcentaje de avance dentro de una etapa.
- **Tamaño máximo por archivo**: se fija en la configuración en el plan, con margen sobre los
  ~64 KB de un `.npy` de 128 × 128 en float32.
- **Biblioteca 3D**: el visor usa Three.js, como pide la descripción. Cómo se entrega al
  navegador (copia local o red de distribución pública gratuita) se decide en el plan.
- **Mensajes**: los mensajes al usuario van en español; las rutas, los campos y los nombres
  de código, en inglés (Principio III).

## Out of Scope

- Autenticación, usuarios y permisos.
- Formulario web de carga (`index.html`): esta funcionalidad expone la API y el visor; la
  carga se hace con cualquier cliente HTTP o con la documentación interactiva.
- Listado paginado de estudios.
- Dibujo del volumen, cortes o ventanas de intensidad en el visor.
- Reprocesar un estudio `failed` o `completed`: se borra y se crea de nuevo.
- Reemplazar proyecciones ya subidas.
- Cola de trabajos externa, reintentos automáticos y procesamiento en varios procesos.
- Modelo de hígado.
- Guardar `region_id` en la base.
- Ocultar o mostrar lesiones una por una en el visor (solo se resaltan).
