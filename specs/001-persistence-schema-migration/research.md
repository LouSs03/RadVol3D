# Research: Migración de la capa de persistencia

Cada decisión indica qué se eligió, por qué y qué otras opciones se descartaron. Las cifras salen
del repositorio o de una medición con su fecha. Los valores elegidos sin medición se marcan como
**decisión**.

## R1. Grupo de conexiones sobre el pooler de sesión

**Decisión:** se usa `psycopg_pool.ConnectionPool`, síncrono, con `DATABASE_URL` apuntando al
pooler de sesión de Supabase.

- **Apertura:** el grupo se crea con `open=False` y se abre en `Database.open()` con
  `wait=True`. Así el arranque falla enseguida si la base no responde (FR-012).
- **Tamaño:** `min_size=1` y `max_size=4`. Es una **decisión**: el repositorio no dice cuántos
  clientes admite el pooler en el plan gratuito, y las pruebas de concurrencia deben
  confirmarlo.
- **Tiempo de espera al abrir:** 10 s. También es una **decisión**.
- **Sentencias preparadas:** psycopg las usa automáticamente, y el modo sesión las admite, así
  que se deja `prepare_threshold` en su valor por defecto. Si algún día se cambia al pooler de
  transacción, habría que poner `prepare_threshold=None`.

**Por qué:** el servicio atiende peticiones simultáneas, y existe la carpeta `tests/concurrency/`.
Con una sola conexión compartida, todas las peticiones se ejecutarían de a una. Los routers y
`StudyService` son síncronos, así que el grupo también lo es.

**Alternativas descartadas:**

- **Una conexión con candado.** Ejecuta las peticiones de a una.
- **`AsyncConnectionPool`.** El resto del código es síncrono.
- **Pooler de transacción (puerto 6543).** Obliga a desactivar las sentencias preparadas, y lo
  que se pidió fue el de sesión.

**Peso de la dependencia nueva:** `psycopg_pool-3.3.3-py3-none-any.whl` pesa 40 304 bytes. Es
Python puro (medido con `pip download --no-deps` el 2026-10-09). Se declara como extra del
paquete ya existente: `psycopg[binary,pool]>=3.1`.

## R2. Unidad de trabajo y repositorios

**Decisión:** `Database.transaction()` es un gestor de contexto. Toma una conexión del grupo,
abre `conn.transaction()` y la entrega. Cada repositorio recibe esa conexión en su constructor y
nunca abre una propia. Los almacenes crean sus repositorios dentro de una misma unidad de
trabajo, y eso hace atómicas las operaciones de varias tablas (FR-005, FR-011).

**Alternativas descartadas:**

- **Que cada repositorio pida su propia conexión.** Impide que dos repositorios confirmen juntos.
- **Una conexión global por proceso.** Descartada por la misma razón que en R1.

## R3. Traducción de errores de la base

**Decisión:** `persistence/database_errors.py` concentra la traducción en una función. La función
recibe un `psycopg.Error` y devuelve el error del dominio que corresponde, según la clase del
error y `error.diag.constraint_name`. La correspondencia completa está en
[data-model.md](data-model.md#restricciones-y-errores-del-dominio). Si una violación de
integridad no está en la tabla, se traduce a `PersistenceError`. `OperationalError` y
`psycopg_pool.PoolTimeout` se traducen a `DatabaseUnavailableError`.

El error del dominio se lanza **sin encadenar** (`raise ... from None`). Su mensaje lo escribe el
proyecto, en español, y nunca copia el de psycopg. Solo se registran el `sqlstate` y el nombre de
la restricción.

**Por qué:** el mensaje de psycopg incluye `DETAIL: Key (national_id)=(12345678) already exists`.
Copiarlo, o dejarlo en `__cause__` para que aparezca en una traza, filtraría el DNI (FR-025) y
otros valores.

**Cómo se prueba sin base:** `tests/fixtures/fake_database.py` define subclases de las
excepciones de `psycopg.errors` (`UniqueViolation`, `CheckViolation`, etc.). Cada subclase
redefine `diag` para devolver el nombre de restricción que se le pase.

**Alternativa descartada:** consultar antes de escribir, en lugar de traducir errores. Duplica
las reglas del esquema y es vulnerable a carreras.

## R4. Los repositorios trabajan con claves naturales

**Decisión:** los repositorios reciben y devuelven claves naturales: `study_code`,
`patient_code`, el nombre del órgano y el par `(model_name, version)`. Los identificadores
seriales se resuelven dentro del SQL, con subconsultas o uniones, y no salen de la capa. Si
una escritura no encuentra el estudio y afecta cero filas, el repositorio lanza
`StudyNotFoundError`.

**Por qué:** la interfaz y los servicios ya identifican los estudios por su código. Sumar ids
seriales a las entidades ataría el dominio a la base. `Organ.organ_id` se mantiene porque ya
existe y no estorba.

## R5. Código consecutivo de paciente y búsqueda o alta por DNI

**Decisión:** todo ocurre en la unidad de trabajo del registro del estudio.

1. `select pg_advisory_xact_lock(<constante>)` serializa las altas de pacientes. El candado se
   libera solo al confirmar o revertir.
2. Si hay DNI, se busca el paciente. Si existe, se devuelve tal como está.
3. Si no existe, se calcula
   `max(patient_code) where patient_code ~ '^PAC[0-9]{6}$'` y se le suma 1. Con ancho fijo, el
   orden lexicográfico coincide con el numérico.
4. El código nuevo se valida con `^PAC[0-9]{6}$`. Si pasaría de `PAC999999`, se lanza
   `PatientCodeExhaustedError`.
5. Si no hay ningún dato personal, se devuelve `PAC000000`. Si esa fila falta, se lanza
   `PersistenceError` indicando que hay que aplicar `001_create_tables.sql`.

Un nombre o apellido en blanco (solo espacios) cuenta como dato ausente.

**Por qué:** el candado cubre las dos carreras posibles, dos códigos iguales y dos altas del mismo
DNI, sin cambiar el esquema.

**Alternativas descartadas:**

- **Una secuencia de PostgreSQL.** Exige una migración `002`, y deja huecos cuando una
  transacción se revierte, así que el código dejaría de ser consecutivo.
- **Reintentar al chocar con la unicidad.** Es más código y no resuelve el caso del DNI.

## R6. Configuración

**Decisión:** se usa `pydantic_settings.BaseSettings`.

- **Campos:** `database_url` y `supabase_service_key` como `SecretStr`, y `supabase_url` y
  `storage_bucket` como `str`. Todos tienen `min_length=1`, así que una variable vacía cuenta
  como faltante.
- **Origen:** las variables se leen de `.env` en la raíz del repositorio, ubicado con
  `Path(__file__).parents[3]`, y del entorno. El entorno tiene prioridad.
- **Carga diferida:** `get_settings()` carga la configuración la primera vez que se llama y la
  guarda (`functools.cache`). Importar el módulo no falla aunque falte `.env`, lo que permite
  probarlo.
- **Errores:** si falta algo, se captura el `ValidationError` y se lanza
  `ConfigurationError("Falta la variable DATABASE_URL en .env", …)` sin encadenar. El mensaje se
  arma con los nombres de los campos que fallaron, nunca con el texto de pydantic, que incluye
  `input_value` y podría contener otras claves.

## R7. Almacenamiento de objetos

**Decisión:** `ObjectStorage` recibe un cliente de bucket que se le inyecta (la interfaz de
`storage3`). En producción, `ObjectStorage.from_settings(settings)` lo construye con
`create_client(url, key).storage.from_(bucket)`. Operaciones:

- **Subir:** `upload(path, data, file_options={"upsert": "true", "content-type": …})`. Con
  `upsert`, subir a una ruta ocupada reemplaza el archivo (FR-021).
- **Bajar y comprobar:** `download(path)` y `exists(path)`. Los dos están en storage3 2.32.0,
  verificado en el entorno el 2026-10-09.
- **Tipos de contenido:** `.npy` como `application/octet-stream`, `.json` como
  `application/json` y `.glb` como `model/gltf-binary`.
- **Arreglos:** `save_array` y `load_array` usan `numpy.save` y `numpy.load` sobre `BytesIO`,
  siempre con `allow_pickle=False`. Si se lee un `.npy` con objetos, numpy lanza `ValueError`,
  que se traduce a `StorageError` (FR-019).
- **Errores:** `storage3.utils.StorageException` se traduce a `StorageError`. Si el archivo no
  existe, se lanza `StorageObjectNotFoundError`, una subclase.

**Verificado contra el Supabase de prueba (T056):** al bajar un objeto inexistente, Supabase lanza
`storage3.exceptions.StorageApiError`, subclase de `StorageException`, con `status` 404 y `code`
`not_found` (mensaje "Object not found"). `exists` devuelve `False` para ese mismo archivo. Por eso
la captura de `StorageException` es suficiente y `download` consulta `exists` para distinguir "no
existe" de "fallo de acceso". Se podría ahorrar esa segunda llamada leyendo `status == "404"`, pero
no se hizo para no atar la capa al texto de un error de un tercero.

## R8. Orden entre el bucket y la base

**Decisión.** Al registrar un estudio (`study_metadata_store.register_study`), dentro de una
unidad de trabajo:

1. Valida el código y las proyecciones, sin tocar nada.
2. Identifica o registra al paciente (R5).
3. Inserta el estudio. Si el código ya existe, falla aquí, **antes de subir nada**, y los
   archivos del estudio original quedan intactos.
4. Sube las cuatro proyecciones.
5. Inserta las filas de proyección y prepara las cuatro etapas.
6. Confirma.

Si falla algo entre los pasos 4 y 6, se revierte la transacción. Los archivos que ya se habían
subido quedan huérfanos, pero no aparecen como estudio. Como las rutas son deterministas, un
reintento con el mismo código los reemplaza.

Al guardar un resultado (`result_store.save_result`), primero se valida todo sin tocar nada y se
comprueba que el estudio existe (transaccion corta que suelta la conexion), para no subir
archivos de un estudio inexistente. Despues se suben los cinco archivos.
Después, en una unidad de trabajo, se insertan las lesiones, se registra el modelo de
segmentación y se marcan las etapas 3 y 4 como `completed`. Si la unidad falla, las etapas
quedan como estaban (FR-048).

**Alternativa descartada:** compensar borrando archivos. Exige una operación de borrado que la
especificación no incluye, y el reintento ya cubre el caso.

## R9. Etapas

- **Nombre:** `stage_name` es `StageNumber(n).name.lower()`, es decir `preprocessing`,
  `reconstruction`, `segmentation` y `meshing`.
- **Preparación:** `prepare_stages` usa `insert … on conflict (study_id, stage_number) do
  nothing`, así que repetirla no duplica filas.
- **Horas:** al pasar a `running` se registra `started_at = now()`. Al pasar a `completed`,
  `skipped` o `failed` se registra `finished_at = now()`. Una etapa puede terminar sin haber
  empezado (por ejemplo, `skipped`): queda con `started_at` nulo, y nunca se inventa esa hora.
- **Modelo:** `result_store` registra en la etapa 3 el modelo de segmentación, tomado de
  `summary["model_name"]` y `summary["model_version"]`.

## R10. Estrategia de pruebas

**Unitarias** (`tests/unit/persistence/`, marca `unit`, sin red):

- **Doble de la base:** `fake_database.FakeConnection` guarda cada `execute(sql, params)` y
  devuelve filas preparadas, o lanza un error de psycopg con su restricción (R3). Verifica que
  los parámetros sean los correctos, que las filas se conviertan bien en entidades y que los
  errores se traduzcan. No verifica el SQL: eso lo hace la integración.
- **Doble del bucket:** `fake_object_storage.InMemoryBucket` imita `upload`, `download` y
  `exists` de storage3, y sirve para probar `ObjectStorage`. Los almacenes, en cambio, se prueban
  con un `ObjectStorage` construido sobre ese bucket en memoria.
- Hay una prueba por repositorio, como se pidió, y una por cada uno de los demás componentes
  (FR-053).

**Integración** (`tests/integration/persistence/`, marca `integration`):

- **Configuración:** las pruebas leen **solo** `.env.test`, nunca `.env`. Si `.env.test` no
  existe, se omiten. Así ninguna prueba puede escribir en la base real por error. Se agrega
  `.env.test.example` y se suma `.env.test` a `.gitignore`.
- **Datos:** usan códigos de estudio con el prefijo `it_` y borran lo que crearon al terminar.
  Ese SQL de limpieza vive solo en las pruebas.

## R11. Cambios en el dominio

Ver [data-model.md](data-model.md). En resumen:

- **Entidades nuevas:** `Patient`, `PatientDetails`, `Model` y `StoredResult`.
- **Campos nuevos:** `patient`, `model` y `grid_size` en `Study`, y `model` en
  `ProcessingStage`.
- **Datos personales ocultos:** los campos personales se declaran con `field(repr=False)`, para
  que imprimir o registrar un paciente no muestre su nombre ni su DNI.
- **Errores nuevos** en `exceptions.py`.

Todos los campos nuevos tienen valor por defecto, así que el código existente, incluidos
`tests/fixtures/fake_strategies.py` y los routers, no se rompe.

## R12. Correspondencia de `summary.json` con las filas de `lesion`

**Decisión:** `result_store` valida que `summary["regions"]` sea una lista. De cada elemento
exige `location`, `volume_mm3` y `confidence`, y toma `max_diameter_mm` si está. Cada elemento
genera una fila de `lesion` con `mesh_path = <study_code>/meshes/tumor.glb` (FR-047a). Si un
elemento tiene `has_lesion` distinto de `true`, se ignora como defensa. Si falta alguna clave
obligatoria, se lanza `InvalidLesionError` y no se guarda nada. `summary.json` se sube tal como
llegó, serializado con `json.dumps(…, ensure_ascii=False)`.

## R14. Consulta del resultado de un estudio sin resultado

**Decisión:** `get_result` devuelve un `StoredResult` vacío (rutas en `None`, `lesions == []`)
cuando el estudio existe y no tiene resultado guardado. Solo lanza `StudyNotFoundError` si el
estudio no existe (FR-049, decisión del usuario).

**Cómo se sabe que hay resultado:** las etapas 3 y 4 del estudio están en `completed`. Esa
decisión es de este diseño, no del usuario. `save_result` marca esas etapas en la misma unidad
de trabajo que inserta las lesiones (R8, FR-048), así que el marcador se confirma junto con las
filas o no se confirma.

**Por qué no consultar el bucket:**

- Un guardado fallido puede haber subido archivos antes de revertirse. Si se usara el bucket,
  la consulta mostraría rutas sin lesiones ni etapas completadas.
- Evita hasta cinco llamadas de red por consulta, y la interfaz consulta mientras el estudio se
  procesa.

**Alternativa descartada:** `exists` por cada archivo. Es más fiel a lo que hay en el bucket,
pero contradice la atomicidad de FR-048.

**Limitación conocida:** si otro código marcara las etapas 3 y 4 como `completed` sin llamar a
`save_result`, la consulta devolvería las cinco rutas sin que los archivos existan. Hoy solo
`save_result` lo hace.

## R13. Conexión con la aplicación (fuera de alcance)

`api/dependencies.py` no puede construir repositorios, porque `api` no puede importar
`persistence`. El armado tiene que pasar por una función de `services/` que reciba la
configuración y devuelva `StudyService`, y `lifespan` la usaría para abrir y cerrar la base.
Esta funcionalidad deja listo `Database.open()` / `close()`, y el armado queda para la
funcionalidad de servicios.

## R15. Registros que pueden mostrar la clave de servicio

**Hallazgo (T057, 2026-10-09):** al correr la suite de integración con el registro en DEBUG, la clave
de servicio aparecía 228 veces en la salida. Todas en registros `DEBUG` de `hpack` (la librería de
compresión de cabeceras de HTTP/2 que usa Supabase), que escribe cada cabecera enviada, incluida
`apikey`. Con cualquier nivel superior a DEBUG, 0 apariciones. No lo escribe el código del proyecto,
pero activar DEBUG en producción habría llevado la clave a los registros.

**Decisión:** `ObjectStorage.from_settings` sube el logger `hpack` a WARNING antes de crear el
cliente, sin bajar un nivel más estricto que ya estuviera configurado. Con eso, la clave pasó de 228 a
0 apariciones incluso con DEBUG forzado.

**Lo que no se tocó:** `httpx` registra en INFO la URL de cada petición (la URL del proyecto, que es
un endpoint público y no una credencial). Con el nivel de registro por defecto no aparece; solo si se
baja a INFO o DEBUG. Si el equipo quisiera ocultarla también, bastaría subir `httpx` a WARNING.

**Alternativa descartada:** configurar el nivel solo en las pruebas (`conftest.py`). Protegería la
suite pero no a la aplicación en ejecución, que es donde está el riesgo real.
