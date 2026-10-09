# Diccionario de datos

Una seccion por tabla. Para cada campo: nombre, tipo, si acepta nulos, valor por defecto,
clave, que significa y de donde sale.

Este documento se genero a partir de `docs/database/schema/001_create_tables.sql` y de las
migraciones que se aplican encima (`002_add_lesion_organ.sql`): los tipos, los nulos, los valores
por defecto, las restricciones y las descripciones salen de ahi (de los `comment on column`; donde
el SQL no trae comentario, la descripcion se dedujo del esquema). La columna **Origen** sale del
codigo de `src/radvol3d/persistence/`. Si el SQL cambia, hay que actualizar este documento.

## Relaciones

```
patient 1 ---- * study * ---- 1 organ
                   |  *
                   |  +---- 0..1 model      (modelo de reconstruccion)
                   |
                   +--- 1 ---- * projection        (las cuatro de entrada)
                   +--- 1 ---- * processing_stage  (las cuatro etapas; cada una puede apuntar a un model)
                   +--- 1 ---- * lesion
```

Borrar un estudio borra en cascada sus proyecciones, etapas y lesiones. La capa de persistencia no
ofrece borrado; la cascada protege a quien lo haga a mano o desde las pruebas.

## patient

Paciente al que pertenece un estudio.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `patient_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `patient_code` | `varchar(16)` | no | - | unica | Codigo interno del paciente. Obligatorio. | PatientRepository: PAC mas seis digitos consecutivos al crear un paciente. PAC000000 viene sembrado |
| `first_name` | `varchar(80)` | si | - | - | Nombre. Opcional. | lo escribe la persona en la interfaz (PatientDetails) |
| `last_name` | `varchar(80)` | si | - | - | Apellido. Opcional. | lo escribe la persona en la interfaz (PatientDetails) |
| `national_id` | `varchar(16)` | si | - | unica | DNI. Opcional y unico cuando se registra. | lo escribe la persona en la interfaz (PatientDetails) |
| `created_at` | `timestamptz` | no | `now()` | - | momento en que se registro el paciente | valor por defecto de la base |

**Restricciones**

- `patient_national_id_format`: `check (national_id is null or national_id ~ '^[0-9]{8}$')`
- `patient_code_format`: `check (patient_code ~ '^[A-Za-z0-9_-]{1,16}$')`

**Quien la referencia**

- `study.patient_id`

## organ

Organo sobre el que se hace un estudio.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `organ_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `name` | `varchar(32)` | no | - | unica | lung o liver. Alcance vigente: dos organos. | sembrado por el esquema: lung y liver |
| `anatomical_region` | `varchar(64)` | no | - | - | Region anatomica que cubre el estudio. | sembrado por el esquema: thorax y upper abdomen |

**Restricciones**

- `organ_name_allowed`: `check (name in ('lung', 'liver'))`

**Quien la referencia**

- `study.organ_id`

## model

Catalogo de modelos. Una fila por version.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `model_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `model_name` | `varchar(64)` | no | - | - | Nombre de la estrategia que corrio. | ModelRepository.get_or_create; lo recibe de la estrategia que corrio o del model_name de summary.json |
| `version` | `varchar(32)` | no | - | - | Version del modelo. Con el nombre, identifica la fila. | ModelRepository.get_or_create; de la estrategia o del model_version de summary.json |
| `trained_on` | `date` | si | - | - | Fecha de entrenamiento. Dato real, no estimado. | solo si se conoce; nunca se estima |
| `description` | `text` | si | - | - | descripcion libre del modelo. Opcional | solo si llega |
| `created_at` | `timestamptz` | no | `now()` | - | momento en que se registro la version en el catalogo | valor por defecto de la base |

**Restricciones**

- `model_name_version_unique`: `unique (model_name, version)`

**Quien la referencia**

- `study.model_id`
- `processing_stage.model_id`

## study

Un estudio: un organo de un paciente, procesado una vez.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `study_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `study_code` | `varchar(64)` | no | - | unica | Identificador que usa la interfaz. Letras, digitos, guion y guion bajo. | lo elige la interfaz; se valida antes de tocar la base o el bucket |
| `patient_id` | `integer` | no | - | FK a `patient.patient_id` | paciente al que pertenece el estudio | StudyRepository.create, a partir del patient_code que devuelve PatientRepository |
| `organ_id` | `integer` | no | - | FK a `organ.organ_id` | organo estudiado | StudyRepository.create, a partir del nombre del organo |
| `model_id` | `integer` | si | - | FK a `model.model_id` | Modelo de reconstruccion usado. Nulo mientras no se procesa. | StudyRepository.mark_completed (modelo de reconstruccion). Nulo hasta entonces |
| `status` | `varchar(16)` | no | `'pending'` | - | pending, processing, completed o failed. | valor por defecto pending; la tuberia lo cambia con update_status y mark_completed |
| `grid_size` | `smallint` | si | - | - | Lado del volumen reconstruido, en voxeles. | StudyRepository.mark_completed |
| `total_time_sec` | `numeric(9, 3)` | si | - | - | Tiempo total del procesamiento, en segundos. | StudyRepository.mark_completed |
| `created_at` | `timestamptz` | no | `now()` | - | momento en que se registro el estudio | valor por defecto de la base |

**Restricciones**

- `study_code_format`: `check (study_code ~ '^[A-Za-z0-9_-]{1,64}$')`
- `study_status_allowed`: `check (status in ('pending', 'processing', 'completed', 'failed'))`
- `study_total_time_positive`: `check (total_time_sec is null or total_time_sec >= 0)`

**Quien la referencia**

- `projection.study_id`: al borrar la fila, se borran en cascada las de `projection`
- `processing_stage.study_id`: al borrar la fila, se borran en cascada las de `processing_stage`
- `lesion.study_id`: al borrar la fila, se borran en cascada las de `lesion`

**Indices**

- `idx_study_patient` sobre `patient_id`
- `idx_study_organ` sobre `organ_id`
- `idx_study_model` sobre `model_id`
- `idx_study_status` sobre `status`

## projection

Las cuatro proyecciones de entrada de un estudio.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `projection_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `study_id` | `integer` | no | - | FK a `study.study_id` (cascada) | estudio al que pertenece. Se borra en cascada con el estudio | se resuelve a partir del study_code |
| `angle_degrees` | `smallint` | no | - | - | Angulo de la proyeccion: 0, 45, 90 o 135. | angulo de cada proyeccion que sube la persona |
| `file_path` | `text` | no | - | - | Ruta del .npy dentro del bucket de Storage. | storage_layout.projection_path |
| `original_name` | `varchar(255)` | si | - | - | Nombre del archivo que subio el usuario. | nombre del archivo que subio la persona |

**Restricciones**

- `projection_angle_allowed`: `check (angle_degrees in (0, 45, 90, 135))`
- `projection_study_angle_unique`: `unique (study_id, angle_degrees)`

**Indices**

- `idx_projection_study` sobre `study_id`

## processing_stage

Las cuatro etapas de la tuberia por estudio.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `stage_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `study_id` | `integer` | no | - | FK a `study.study_id` (cascada) | estudio al que pertenece. Se borra en cascada con el estudio | se resuelve a partir del study_code |
| `stage_number` | `smallint` | no | - | - | 1 preprocesamiento, 2 reconstruccion, 3 segmentacion, 4 mallas. | ProcessingStageRepository.prepare_stages crea las cuatro |
| `stage_name` | `varchar(32)` | no | - | - | nombre de la etapa: preprocessing, reconstruction, segmentation o meshing | se deriva del numero de etapa |
| `stage_status` | `varchar(16)` | no | `'waiting'` | - | waiting, running, completed, skipped o failed. | valor por defecto waiting; set_status lo cambia |
| `model_id` | `integer` | si | - | FK a `model.model_id` | Modelo que ejecuto esta etapa, cuando corresponde. | set_status (model=...); ResultStore registra aqui el modelo de segmentacion |
| `started_at` | `timestamptz` | si | - | - | momento en que paso a running. Nulo si nunca empezo | set_status: now() al pasar a running |
| `finished_at` | `timestamptz` | si | - | - | momento en que paso a un estado final. Nulo mientras no termina | set_status: now() al pasar a completed, skipped o failed |

**Restricciones**

- `stage_number_allowed`: `check (stage_number between 1 and 4)`
- `stage_status_allowed`: `check (stage_status in ('waiting', 'running', 'completed', 'skipped', 'failed'))`
- `stage_study_number_unique`: `unique (study_id, stage_number)`

**Indices**

- `idx_processing_stage_study` sobre `study_id`

## lesion

Regiones marcadas como lesion por el segmentador.

| Campo | Tipo | Nulo | Por defecto | Clave | Descripcion | Origen |
|---|---|---|---|---|---|---|
| `lesion_id` | `serial` | no | automatico | PK | clave primaria interna | lo genera la base |
| `study_id` | `integer` | no | - | FK a `study.study_id` (cascada) | estudio al que pertenece. Se borra en cascada con el estudio | se resuelve a partir del study_code |
| `location` | `varchar(128)` | no | - | - | Posicion geometrica dentro del volumen. No es un lobulo anatomico. | campo location de cada elemento de regions en summary.json |
| `volume_mm3` | `numeric(12, 2)` | no | - | - | Volumen de la lesion en milimetros cubicos. | campo volume_mm3 de la region |
| `max_diameter_mm` | `numeric(8, 2)` | si | - | - | Diametro maximo. Opcional: el segmentador puede no entregarlo. | campo max_diameter_mm de la region. Opcional |
| `confidence` | `numeric(5, 4)` | no | - | - | Confianza media de la region, entre 0 y 1. | campo confidence (probabilidad media) de la region |
| `mesh_path` | `text` | si | - | - | Ruta del .glb de la lesion dentro del bucket. Es el unico enlace entre la fila y su malla: la tabla no guarda `region_id`. | storage_layout.lesion_mesh_path: `<study_code>/meshes/lesion_<NNN>.glb`, una por lesion, numeradas desde 001 en el orden del resumen (desde la funcionalidad 004; antes todas apuntaban a `tumor.glb`) |
| `created_at` | `timestamptz` | no | `now()` | - | momento en que se guardo la lesion | valor por defecto de la base |
| `organ` | `varchar(32)` | no | - | - | Órgano al que pertenece la lesión: lung o liver. | migracion 002. LesionRepository la toma del organo del estudio en el mismo insert; no la recibe del segmentador |

**Restricciones**

- `lesion_volume_positive`: `check (volume_mm3 > 0)`
- `lesion_confidence_range`: `check (confidence >= 0 and confidence <= 1)`
- `lesion_organ_allowed`: `check (organ in ('lung', 'liver'))` (migracion 002)

**Indices**

- `idx_lesion_study` sobre `study_id`

## Seguridad a nivel de fila

Esta activada en las siete tablas y no hay ninguna politica definida. Sin politicas, ninguna clave
publica puede leer ni escribir. El servicio entra con la clave de servicio (`SUPABASE_SERVICE_KEY`),
que no pasa por estas reglas. Si algun dia la interfaz consulta Supabase directamente, ahi van las
politicas.

## Datos iniciales

El mismo script siembra, con `on conflict ... do nothing` para poder repetirlo:

| Tabla | Filas |
|---|---|
| `patient` | `PAC000000`, sin nombre, apellido ni DNI: el paciente de referencia para estudios sin datos personales |
| `organ` | `lung` (`thorax`) y `liver` (`upper abdomen`) |

## Verificacion del esquema

Resultado de la consulta de verificacion de `001_create_tables.sql`,
ejecutada el 2026-10-08 en Supabase:

| table_name       | rows |
| ---------------- | ---- |
| lesion           | 0    |
| model            | 0    |
| organ            | 2    |
| patient          | 1    |
| processing_stage | 0    |
| projection       | 0    |
| study            | 0    |

Repetida el 2026-10-09 en el proyecto de Supabase de prueba, que estaba vacio, con el mismo
resultado: siete tablas, `patient` con 1 fila, `organ` con 2 y el resto en 0.

La migracion `002_add_lesion_organ.sql` estaba aplicada en el Supabase de prueba el 2026-10-09:
`lesion.organ` es `character varying(32)`, no nula, con `lesion_organ_allowed` y su comentario, y
ninguna fila con `organ` nulo. En la base real se aplica despues de fusionar la funcionalidad 004.
