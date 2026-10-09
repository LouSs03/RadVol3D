# Research: Capa de servicios y tubería de procesamiento

Fase 0 de `/speckit-plan`. Cada decisión tiene el formato Decisión / Motivo / Alternativas.
Las mediciones se hicieron el 2026-10-09 en la laptop de desarrollo (Windows 11, Python 3.13,
CPU, sin GPU), salvo que se indique otra cosa. No son metas de rendimiento: sirven para
dimensionar las pruebas.

## R1. Estructura de `services/`

- **Decisión**: cuatro subpaquetes más dos módulos en la raíz:
  - `services/reconstruction/`, `services/segmentation/` y `services/meshing/`: una interfaz
    y las estrategias concretas de cada etapa;
  - `services/pipeline/`: tubería, filtros, carga de proyecciones y puerto de avance;
  - `services/strategy_factory.py` y `services/study_service.py`;
  - además, `services/service_container.py`, que arma todo al arrancar (R11).

  `services/preprocessing/` desaparece: su único archivo, `projection_loader.py`, pasa a
  `services/pipeline/`, porque el preprocesamiento es el primer filtro de la tubería.
  `services/processing_pipeline.py` pasa a `services/pipeline/processing_pipeline.py`.
- **Motivo**: es la estructura que pidió el usuario. Agrupa lo que cambia junto: una estrategia
  nueva toca solo su carpeta, y un cambio en el orden de las etapas, solo `pipeline/`.
- **Alternativas**: dejar `processing_pipeline.py` en la raíz, como dice hoy la constitución.
  Se descarta porque el usuario pidió `services/pipeline`. El cambio de ruta se resuelve con una
  enmienda PATCH de la constitución (ver plan.md, Constitution Check).

## R2. PyTorch opcional y carga perezosa

- **Decisión**: `torch` va como extra `ml` en `pyproject.toml`
  (`[project.optional-dependencies] ml = ["torch>=2.6"]`) y no entra en `requirements.txt`.
  Ningún módulo que se importe al arrancar sin modelos importa `torch` en su nivel superior.
  Solo cuatro módulos lo importan:
  - `reconstruction/en1_network.py`
  - `reconstruction/en1_reconstructor.py`
  - `segmentation/lung_unet_network.py`
  - `segmentation/lung_segmenter.py`

  Las estrategias (`neural_en1_strategy.py`, `lung_unet_strategy.py`) los importan dentro de
  su método de construcción `from_weights(...)`, nunca en el nivel superior.
- **Motivo**: así el CI no instala torch, y `api/` puede importar `services` sin arrastrar torch
  (Principio I). La fábrica y el contenedor se pueden importar y probar sin torch.
- **Alternativas**:
  - Instalar torch CPU en el CI (≈ 540 MB instalado). Se descarta porque el usuario decidió
    que el CI no lo instale.
  - Importar torch con `try/except ImportError` en el nivel superior. Se descarta porque oculta
    el error hasta la primera inferencia.

## R3. Peso declarado de las dependencias nuevas (constitución, "Servicios y dependencias")

Se midió en la laptop de desarrollo (Windows, Python 3.13): el tamaño instalado con
`du -sh` y la rueda descargada con `pip download`. En el CI (Linux, Python 3.11) los números
pueden variar.

| Dependencia | Dónde | Rueda | Instalado | Para qué |
|---|---|---|---|---|
| `torch` 2.14.1+cpu | extra `ml` | — | 539 MB | inferencia de EN-1 y EN-2 |
| `scikit-image` 0.26.0 | `requirements.txt` | 11,9 MB | 25 MB, más networkx 18 MB, pillow 16 MB, imageio 2,7 MB y tifffile 2,4 MB | marching cubes y Otsu |
| `trimesh` 5.1.1 | `requirements.txt` | 0,75 MB | 4,5 MB | exportar `.glb` |

`numpy` y `scipy` ya estaban. Las tres son gratuitas y de código abierto. La declaración se
repite en la descripción del pull request.

## R4. Escala de entrada de las proyecciones (Q2 = A)

- **Decisión**: el preprocesamiento acepta solo `.npy`. Antes de `np.load(...,
  allow_pickle=False)` comprueba la firma mágica `\x93NUMPY`. Así un PNG recibe un mensaje
  claro ("solo se acepta .npy en el convenio de TA-2") y no un error de numpy. Después
  exige un dtype numérico, la forma `(128, 128)` y valores finitos, y convierte a `float32`.
  No reescala nada. `config.ACCEPTED_FORMATS` pasa a `(".npy",)`.
- **Motivo**: EN-1 se entrenó y se midió con integrales de línea del convenio de TA-2.
  Normalizar a [0, 1] cambia la entrada y la salida sin avisar.
- **Alternativas**: validar un rango de valores. Se descarta porque el repositorio no fija ese
  rango, y fijarlo sería inventar un dato (Principio V).

## R5. Admisión antes de registrar

- **Decisión**: el preprocesamiento se divide en dos pasos:
  1. **Admisión**: `ProjectionLoader.parse`. Lee y valida cada archivo, y comprueba que estén
     los cuatro ángulos sin repetidos. Corre antes de registrar el estudio.
  2. **Filtro de la etapa 1**: `PreprocessingFilter`. Ordena por ángulo y apila en
     `(4, 128, 128)`. Corre dentro de la tubería y se registra como etapa 1.

  La fábrica también se consulta antes de registrar. Así, el órgano `liver` o un modelo no
  cargado fallan sin crear el estudio.
- **Motivo**: la especificación exige que una entrada inválida no cree el estudio (historia 2,
  escenario 1). `register_study` ya necesita los arreglos leídos, así que la lectura tiene que
  ocurrir antes de registrar.
- **Alternativas**: registrar primero y validar en la etapa 1. Se descarta porque dejaría un
  estudio `failed` por cada archivo mal subido.

## R6. Pipes and Filters y registro de cada etapa

- **Decisión**:
  - **Filtros.** Cada etapa es un filtro con `stage_number`, `apply(data) -> data` y,
    opcionalmente, el modelo que usa. Los datos que pasan de un filtro a otro (`PipelineData`)
    son inmutables y propios de cada corrida.
  - **Bucle de `ProcessingPipeline.run`.** Para cada filtro:
    1. llama a `progress.stage_started`;
    2. corre el filtro;
    3. llama al paso de guardado de esa etapa: el volumen después de la etapa 2 y el resultado
       después de la etapa 4;
    4. llama a `progress.stage_completed`, con el modelo de la etapa si lo tiene.
  - **Si algo falla**, llama a `progress.stage_failed(n)`. Esa llamada marca la etapa `failed`,
    las siguientes `skipped` y el estudio `failed`, todo en una sola unidad de trabajo. Después
    la tubería lanza `StageFailedError`.
  - **El puerto `PipelineProgress`** es un `Protocol` en `services/pipeline/progress.py`. Lo
    implementan `PersistenceProgress`, en servicios, y un doble en `tests/fixtures/`, que
    guarda los eventos en una lista.
- **Motivo**: la tubería no sabe qué estrategias le tocaron ni si la persistencia es real.
  Los filtros no guardan estado, así que dos estudios a la vez no comparten datos (FR-020).
- **Alternativas**: que cada estrategia registre su propia etapa. Se descarta porque mezcla
  la persistencia con el algoritmo y obliga a repetir el registro en cada estrategia.

## R7. `save_result` deja de marcar las etapas (cambio en la persistencia)

- **Decisión**:
  - **Qué cambia.** `ResultStore.save_result` sube los cinco archivos e inserta las lesiones en
    una unidad de trabajo, pero ya no cambia el estado de las etapas 3 y 4 ni registra el
    modelo de la etapa 3. Eso lo hace la tubería con `stage_completed`.
  - **Qué no cambia.** La regla de `get_result` ("hay resultado si las etapas 3 y 4 están en
    `completed`") sigue igual. Como la etapa 4 se cierra después de `save_result`, el resultado
    aparece completo o no aparece.
- **Motivo**: hoy `save_result` vuelve a marcar la etapa 3 como `completed` y pisa su
  `finished_at` con la hora del fin de la etapa 4. Así la etapa 3 parece durar también lo que
  duraron las mallas, y FR-007 deja de cumplirse.
- **Alternativas**:
  - Que la tubería no cierre la etapa 3 hasta `save_result`. Se descarta porque la etapa 3
    seguiría en `running` mientras corren las mallas.
  - Que `save_result` no toque la etapa 3 si ya está en `completed`. Se descarta porque deja dos
    dueños del mismo estado.

  Las pruebas unitarias y de integración de `result_store` se actualizan en el mismo cambio.

## R8. Borrado de estudios (FR-015, FR-016)

- **Decisión**: `StudyMetadataStore.delete_study(study_code)` hace todo en una transacción:
  1. Bloquea la fila del estudio con `select ... for update` y lee su estado. Si no existe,
     lanza `StudyNotFoundError`. Si está en `processing`, lanza `StudyInProgressError`.
  2. Borra la fila de `study`. Las de `projection`, `processing_stage` y `lesion` caen en
     cascada, porque el esquema ya declara `on delete cascade`.
  3. Borra del bucket las diez rutas deterministas de `storage_layout`, con
     `ObjectStorage.remove_many` (nuevo).
  4. Confirma.

  Si el bucket falla, la transacción se revierte y el estudio sigue en pie, así que el borrado
  se puede reintentar: quitar una ruta que ya no existe no es un error. Los pacientes y los
  modelos no se tocan.
- **Motivo**: es el mismo patrón que `register_study` (R8 de 001), y deja el sistema
  consistente ante cualquier fallo. Como las rutas son deterministas, no hace falta listar el
  bucket.
- **Alternativas**:
  - Borrar primero los archivos y después la fila. Se descarta porque, si falla la base, queda
    un estudio sin archivos.
  - Borrar primero la fila y después los archivos, fuera de la transacción. Se descarta porque,
    si falla el bucket, quedan archivos huérfanos y el borrado ya no se puede reintentar.

## R9. Avance del estudio desde servicios (cambio en la persistencia)

- **Decisión**: se crea `persistence/processing_progress_store.py` con
  `ProcessingProgressStore(database)`, que ofrece:
  - `start_processing(code)`
  - `start_stage(code, n)`
  - `complete_stage(code, n, model_name=None, model_version=None)`
  - `fail_from_stage(code, n)`
  - `complete_study(code, model_name, model_version, grid_size, total_time_sec)`
  - `register_model(model_name, version, trained_on=None, description=None) -> Model`

  Cada método es una unidad de trabajo sobre los repositorios que ya existen. Cuando recibe un
  modelo, hace `get_or_create` antes de enlazarlo, porque `set_status` exige que el modelo esté
  registrado.
- **Motivo**: los repositorios reciben la conexión de una unidad de trabajo. Abrir
  transacciones y combinar repositorios es justo lo que ya hacen los almacenes de la
  persistencia. Así los servicios no manejan conexiones.
- **Alternativas**: que `services/` abra `database.transaction()` y use los repositorios
  directamente. Las capas lo permiten, pero se descarta porque reparte la gestión de
  transacciones entre dos capas.

## R10. Pesos en el bucket de modelos

- **Decisión**:
  - **Configuración.** Una clase nueva, `ModelSettings`, en `persistence/settings.py`, cargada
    con `get_model_settings()`. Ningún campo es obligatorio:
    - `MODEL_BUCKET`
    - `EN1_WEIGHTS_OBJECT`
    - `EN2_WEIGHTS_OBJECT`
    - `MODEL_CACHE_DIR`, por omisión `.cache/models`, ignorada por git
    - `RECONSTRUCTION_STRATEGY`, por omisión `en1`

    `.env.example` y `.env.test.example` las documentan. `config.py` sigue sin leer el entorno.
  - **Descarga.** `persistence/model_weights_store.py` ofrece
    `ModelWeightsStore(storage, cache_dir).fetch(object_path) -> Path`. Si el archivo no está
    en la caché, lo baja una sola vez: escribe un temporal y lo renombra para no dejar un
    archivo a medias.
  - **Rutas en el bucket.** `reconstruction_en1/1.0.0/weights.pth` y
    `segmentation_lung/1.0.0/weights.pth`, y las referencias de regresión bajo `regression/`
    (ver contracts/model_artifacts.md).
- **Motivo**: la constitución dice que solo la persistencia llama a Storage, que los modelos se
  cargan una vez y que ninguna clave entra al código. Los campos son opcionales porque la
  aplicación tiene que arrancar aunque falten los modelos (FR-019).
- **Alternativas**:
  - Guardar los pesos en la imagen o en git. Se descarta porque la especificación lo prohíbe
    (FR-028).
  - Descargarlos en cada arranque sin caché. Se descarta porque son ≈ 48 MB entre los dos en
    cada reinicio.

## R11. Armado al arrancar (lifespan)

- **Decisión**: `services/service_container.py` ofrece
  `build_service_container(settings, model_settings) -> ServiceContainer` y
  `ServiceContainer.close()`. El contenedor:
  - abre `Database` y crea los dos `ObjectStorage` (datos y modelos);
  - construye las estrategias una sola vez con `StrategyFactory.preload()`;
  - registra cada modelo cargado en `model`;
  - arma `StudyService`.

  El `lifespan` de `main.py` lo llama y guarda el contenedor en `app.state.services`.
  `api/dependencies.get_study_service(request)` lo lee de `request.app.state`.
  `main.py` no es una capa, así que importar `services` desde ahí respeta el Principio I.
- **Motivo**: es lo que dejó pendiente el plan 001 ("requiere una función de armado en
  `services/`"). `api/` nunca ve la persistencia.
- **Alternativas**: armar en `api/dependencies.py`. Se descarta porque obligaría a `api/` a
  importar `persistence`, y la prueba de arquitectura lo prohíbe.

## R12. Fábrica: registro de constructores y precarga

- **Decisión**:
  - **Registros.** `StrategyFactory` recibe tres registros:
    - reconstrucción por clave de configuración (`"en1"`);
    - segmentación por `OrganName`, que solo tiene `LUNG`;
    - un constructor de mallas.

    Cada entrada es un constructor sin argumentos.
  - **`preload()`.** Llama a cada constructor una vez. Si uno falla (falta torch, faltan
    pesos o el archivo está corrupto), guarda el motivo sin rutas firmadas ni claves y lo
    registra en el log.
  - **`strategies_for(organ)`.** Devuelve un `StrategySet` con las tres instancias ya
    construidas, o lanza `ModelNotAvailableError` con un mensaje en español. Para `liver`, el
    mensaje dice que el modelo de hígado no existe todavía.
  - **Pruebas.** Las pruebas arman la fábrica con constructores que devuelven los dobles.
- **Motivo**: hay un solo lugar con la tabla órgano → estrategia (Principio II), los modelos se
  cargan una vez (SC-006) y la aplicación arranca aunque falte un modelo (FR-019).
  `LiverUnetStrategy` y `BackprojectionStrategy` siguen siendo esqueletos y no se registran.
- **Alternativas**: construir la estrategia en cada estudio. Se descarta porque recargaría los
  pesos en cada petición.

## R13. Concurrencia

- **Decisión**:
  - Cada estrategia real protege su inferencia con un `threading.Lock` propio, así que dos
    estudios usan el mismo modelo uno después del otro.
  - La tubería, los filtros y `StudyService` no guardan estado entre corridas.
  - La conexión usa el grupo de `psycopg_pool` que ya existe.
- **Motivo**: en CPU, dos inferencias a la vez compiten por los mismos núcleos y duplican la
  memoria, sin ganar tiempo. Serializar es simple, seguro y no carga una copia del modelo por
  estudio, como pide la especificación.
- **Alternativas**:
  - Confiar en que `forward` en modo `eval` sea seguro en paralelo. Se descarta porque no hay
    garantía documentada para el TTA con volteos.
  - Una copia del modelo por hilo. Se descarta porque multiplica la memoria.

## R14. Migración de `models/` sin cambiar la salida

- **Decisión**: cada archivo original se reparte en módulos de servicios, con los
  identificadores en inglés y snake_case. Las operaciones, su orden y las constantes no
  cambian.

  | Original | Destino | Contenido |
  |---|---|---|
  | `en1_inferencia_nuevo (1).py` | `reconstruction/en1_geometry.py` | constantes de TA-1 y TA-2, `project`, `back_project`, `ramp_filter`, `apply_affine`, `ellipsoid_phantom` (solo numpy y scipy) |
  | | `reconstruction/en1_network.py` | `conv_block`, `ResidualUnet3d` (torch) |
  | | `reconstruction/en1_reconstructor.py` | `En1Reconstructor` (`reconstruct`, `prepare_input`, `baseline`, `describe`) (torch) |
  | `en2_inferencia.py` | `segmentation/lung_region_summary.py` | `AXIS_NAMES`, `gaussian_weight_map`, `patch_positions`, `clean_mask`, `describe_position`, `max_diameter_mm`, `summarize_regions`, `InvalidVolumeError` (solo numpy y scipy) |
  | | `segmentation/lung_unet_network.py` | `ResidualBlock`, `SegmentationUnet3d` (torch) |
  | | `segmentation/lung_segmenter.py` | `LungSegmenter` (`segment`, `probability`, `describe`) (torch) |

  - **Lo que se deja.** La línea de comandos y las autopruebas impresas de los originales no se
    migran: las reemplazan las pruebas `ml`. `reconstruir_lote` tampoco: la tubería procesa un
    estudio por corrida.
  - **Claves de los `.pth`.** No se traducen, porque son el formato de los archivos y no
    identificadores de código.
  - **Textos para el usuario.** `location` y `location_note` siguen en español.
- **Motivo**: separar la parte de numpy de la de torch permite probar sin torch la geometría,
  el filtro rampa, el resumen por regiones y la limpieza de máscaras. Eso sube la cobertura
  que mide el CI (R17) sin tocar la lógica. La regresión numérica (R16) comprueba que nada
  cambió.
- **Alternativas**: copiar cada archivo entero a un solo módulo. Se descarta porque todo
  quedaría detrás de `import torch` y fuera de la cobertura del CI.

## R15. Carga segura de los pesos (`weights_only=True`)

- **Decisión**: el código migrado llama a `torch.load(..., weights_only=True)`. Los originales
  usan `weights_only=False`.
- **Motivo**: los pesos vienen de un bucket remoto, y `weights_only=False` ejecuta cualquier
  objeto serializado del archivo. Con `weights_only=True` se comprobó que cargan bien los tres
  archivos: el `.pth` de EN-1, `en2_pulmon_mejor.pth` y el `.pth` de exportación de prueba
  generado con el procedimiento de R18. Los tensores que se leen son los mismos, así que la
  salida numérica no cambia, y la regresión lo verifica. Es el único cambio de lógica de carga
  frente a los originales, y se declara aquí por FR-023a.
- **Alternativas**: dejar `weights_only=False`. Se descarta porque abre ejecución de código
  arbitrario desde el bucket.

## R16. Regresión numérica (FR-034)

- **Decisión**:
  - **Generación.** `scripts/build_regression_reference.py` carga los scripts originales de
    `models/` por ruta, sin modificarlos, y corre en CPU sobre tres casos deterministas sin
    datos de pacientes:
    1. EN-1 sobre las proyecciones del fantoma elipsoide de su autoprueba
       (`proyectar(fantoma_elipsoide())`);
    2. EN-2 sobre el volumen gaussiano de su autoprueba;
    3. EN-2 sobre la salida del caso 1;
    4. `resumen_regiones` y `_limpiar` originales sobre una máscara y una probabilidad
       sintéticas, con tres regiones de tamaños distintos, una de ellas menor que
       `min_voxeles`. Se generan con una semilla fija, sin torch.

    El caso 4 existe porque el volumen gaussiano del caso 2 no produce ninguna lesión (R18).
    Sin él, la regresión no compararía `regions`, `max_diameter_mm` ni la limpieza de
    regiones pequeñas. Su referencia es un JSON pequeño versionado en
    `tests/unit/services/reference/`, y su prueba es `unit`, porque no usa torch.

    El script escribe las salidas en `.npy` y `.json`, y un manifiesto
    (`tests/ml/reference/manifest.json`, versionado) con el SHA-256 de cada archivo, su forma,
    su dtype, la receta de la entrada y las versiones de torch, numpy, scipy y la plataforma.
  - **Almacenamiento.** Los arreglos (≈ 8 MB cada uno) van al bucket de modelos bajo
    `regression/`, no a git. Las pruebas `ml` los bajan con `ModelWeightsStore` y verifican el
    SHA-256 antes de comparar.
  - **Tolerancia.** La máscara debe coincidir exactamente. El volumen y la probabilidad, con
    una diferencia absoluta máxima de `1e-5`. El resumen, campo por campo, salvo los
    identificadores de FR-025.

    Si la plataforma o la versión de torch difieren del manifiesto, la prueba corre igual,
    pero su mensaje de fallo lo dice.
- **Motivo**: la especificación pide una referencia generada una sola vez con los originales.
  Como `models/` no se versiona, la referencia tiene que vivir en algún lugar compartido.
- **Alternativas**:
  - Comparar en vivo contra los originales en cada corrida. Se descarta porque exige tener
    `models/` local y no sirve en otra máquina.
  - Guardar solo estadísticas (media, máximo). Se descarta porque no detecta un vóxel cambiado.

## R17. Cobertura del 80 % sin torch en el CI

- **Decisión**: el CI corre `pytest -m unit --cov=src/radvol3d` y después
  `coverage report --include="src/radvol3d/services/*" --omit=<los cuatro módulos de R2> --fail-under=80`.

  Esos cuatro módulos son los únicos que no se pueden ejecutar sin torch. Los cubren las
  pruebas `ml` en local, con `pytest -m ml --cov`, y su número se informa en el pull request.
- **Motivo**: el usuario pidió las dos cosas, CI sin torch y 80 % en services. Sin omitirlos, el
  80 % no se alcanza en el CI: los cuatro módulos suman ≈ 230 sentencias de las ≈ 740 de
  `services/` (estimación previa a la implementación). Dejarlos tan delgados como permite R14
  es lo que mantiene honesta la omisión.
- **Alternativas**:
  - Omitirlos con `[tool.coverage.report] omit`. Se descarta porque también los ocultaría en
    local.
  - Bajar el umbral. Se descarta porque el usuario fijó el 80 %.

## R18. `.pth` de exportación de EN-2 (Q1 = B)

- **Decisión**: `scripts/export_en2_weights.py`:
  1. Lee `models/en2_pulmon_mejor.pth` y `models/metricas_test.json` con
     `weights_only=True`.
  2. Escribe un `.pth` con estas claves:
     - `pesos` ← `modelo`
     - `canales` ← `canales`
     - `parche` ← `cfg.parche`
     - `rejilla` ← `cfg.rejilla`
     - `mm_por_voxel` ← 2,5
     - `umbral` ← `metricas_test.umbral`
     - `min_voxeles` ← `metricas_test.min_voxeles`
     - `tta` ← `metricas_test.tta`
  3. Deja los opcionales (`solape`, `supervision`, `ventana_hu`) en el valor por omisión del
     módulo, que coincide con `cfg`: `solape_ventana` 0,5 y `supervision` 3.

  El docstring cita la fuente de cada clave. El script no entrena ni modifica los tensores.
  - **Prueba hecha durante este plan.** Con este mismo procedimiento se generó un `.pth` en la
    carpeta temporal y `SegmentadorPulmon`, sin modificar, lo cargó con `strict=True` y
    segmentó el volumen gaussiano de su autoprueba. Resultados:
    - la carga tardó 0,3 s;
    - el archivo se vuelve a abrir con `weights_only=True`;
    - la segmentación tardó 148 s en CPU con 4 hilos;
    - una segunda corrida dio una probabilidad idéntica (`np.array_equal`), así que la
      inferencia es determinista en CPU;
    - el resumen salió con `has_lesion: false`, `lesion_count: 0` y `global_confidence: 1.0`.
      Ese volumen no produce lesiones (ver R16, caso 4).
- **Motivo**: es la respuesta Q1 = B. Además, el `.pth` original se puede reemplazar sin tocar
  código (FR-023).
- **Alternativas**: las opciones A y C de Q1, descartadas por el usuario.

## R19. Mallas (Q3 = A)

- **Decisión**: `MarchingCubesStrategy.build_meshes(volume, mask) -> MeshSet(organ, tumor)`
  produce las dos mallas.
  - **Tumor.** `marching_cubes` sobre la máscara rellenada con un borde de 1 vóxel, con nivel
    0,5, `step_size=1` y `spacing=(2.5, 2.5, 2.5)`.
  - **Órgano.**
    1. Calcula el umbral de Otsu del volumen.
    2. Binariza.
    3. Conserva la componente conexa más grande y rellena sus huecos.
    4. Corre `marching_cubes`, con nivel 0,5 y `step_size=2`.
  - **Coordenadas.** Las dos mallas comparten el mismo sistema: milímetros, ejes en el orden de
    numpy (0, 1, 2) y origen en el centro del volumen. Así se superponen en el visor.
  - **Exportación.** `trimesh.Trimesh(vertices, faces, process=False).export(file_type="glb")`.
  - **Sin superficie.** Si la máscara está vacía, el volumen es constante o Otsu no deja
    superficie, se exporta `trimesh.Trimesh()` vacío. Se comprobó que da un GLB válido de 172
    bytes que trimesh vuelve a abrir. `trimesh.Scene()` vacío, en cambio, lanza `ValueError`.

  Lo que se midió con un volumen gaussiano con ruido de 128³ (scikit-image 0.26, trimesh 5.1):

  | Variante para el órgano | Caras | GLB | Tiempo |
  |---|---|---|---|
  | Isosuperficie directa con Otsu | 1,13 M | 21,2 MB | 0,45 s |
  | Componente más grande, `step_size=1` | 480 k | 8,3 MB | 0,32 s |
  | Componente más grande, `step_size=2` (elegida) | 68 k | 1,2 MB | 0,17 s |

  En cada caso, `marching_cubes` sobre un volumen constante lanza `RuntimeError` y sobre una
  máscara vacía lanza `ValueError`. La estrategia los traduce a la malla vacía.
- **Motivo**: Otsu no fija ningún número a mano (FR-026). La componente más grande descarta
  islas de ruido, y `step_size=2` (5 mm) basta para dar contexto, sin llenar el bucket
  gratuito ni el navegador. El tumor conserva la resolución completa, porque ahí importa el
  detalle.
- **Alternativas**:
  - Simplificar con `fast-simplification` u `open3d`. Se descarta porque son dependencias
    extra que nadie pidió.
  - Umbral fijo en HU. Queda como mejora futura (FR-026a).

## R20. Interfaces de estrategia

- **Decisión**:
  - **`ReconstructionStrategy.reconstruct(projections) -> volume`.** Sin cambios en la firma.
    Se corrige el docstring: la entrada son integrales de línea del convenio de TA-2.
  - **`SegmentationStrategy.segment(volume, study_code) -> SegmentationResult`.**
    `SegmentationResult` gana el campo `summary: Mapping[str, object]`. Se agrega
    `study_code` porque el resumen lo lleva.
  - **`MeshingStrategy.build_meshes(volume, mask) -> MeshSet`.** Reemplaza a `build_mesh(mask)`,
    porque la malla del órgano necesita el volumen.

  Las tres exponen `model_name` y `model_version`. El doble de segmentación pasa a devolver un
  resumen con `model_name`, `model_version` y `regions`, como exige `save_result`.
- **Motivo**: es la firma mínima que cubre FR-022, FR-024 y FR-026. Se mantiene una sola
  interfaz por etapa (Principio II).
- **Alternativas**: dos estrategias de mallas, una por malla. Se descarta porque la tubería
  tendría dos filtros para una sola etapa.

## R21. Errores nuevos y privacidad

- **Decisión**: `domain/exceptions.py` gana dos errores:
  - `StageFailedError(RadVol3DError)`, con los atributos `study_code` y `stage_number`. Su
    mensaje es "La etapa N (nombre) del estudio X falló." y encadena la causa con `from`.
  - `StudyInProgressError(RadVol3DError)`.

  `api/error_handlers.py` les asigna 500 y 409. Es el único toque en `api/` además de los
  imports y `dependencies.py`.

  Los mensajes se arman solo con el código del estudio, el ángulo y la etapa. Los registros de
  log guardan el tipo de la causa, no su texto.
- **Motivo**: FR-031 y FR-032. La tubería nunca recibe datos del paciente, porque el paciente
  solo pasa por `register_study`.
- **Alternativas**: reutilizar `RadVol3DError` genérico. Se descarta porque la presentación no
  podría distinguir los casos.

## R22. Pruebas

- **Decisión**:

  | Carpeta | Marcador | Qué cubre | Necesita |
  |---|---|---|---|
  | `tests/unit/services/` | `unit` | la fábrica, cada filtro, la tubería con el doble de avance, `StudyService` con almacenes falsos, la carga de proyecciones, las mallas reales (scikit-image y trimesh sí están en el CI), la geometría de EN-1 y el resumen de EN-2 | nada |
  | `tests/unit/persistence/` | `unit` | `delete_study`, `ProcessingProgressStore`, `ModelWeightsStore`, `remove_many`, el cambio en `save_result` | nada |
  | `tests/integration/services/` | `integration` | la tubería completa con dobles contra el Supabase de prueba (`.env.test`) | Supabase de prueba |
  | `tests/concurrency/` | `concurrency` | dos estudios a la vez con dobles y la persistencia de prueba, 20 repeticiones (SC-005) | Supabase de prueba |
  | `tests/ml/` | `ml` | la regresión de EN-1 y EN-2, y el estudio de ejemplo con los modelos reales | torch y pesos |
  | `tests/architecture/` | `architecture` | sin cambios | nada |

  `tests/ml/conftest.py` llama a `pytest.importorskip("torch")` y omite las pruebas si faltan
  los pesos. `docs/standards/testing_strategy.md` gana la fila `ml/`.
- **Motivo**: es la tabla de la especificación (FR-033 a FR-035) sobre la estructura de
  carpetas que ya existe.
