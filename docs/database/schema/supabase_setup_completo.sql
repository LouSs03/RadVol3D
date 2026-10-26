-- RadVol3D: esquema completo para un proyecto de Supabase nuevo.
--
-- Junta 001_create_tables.sql y 002_add_lesion_organ.sql en un solo script y
-- agrega los dos buckets de Storage. Se pega entero en el editor SQL de Supabase.
--
-- No borra nada: usa "if not exists" y "on conflict do nothing", asi que se
-- puede correr mas de una vez. Para empezar de cero sobre una base que ya tiene
-- tablas, usar 001_create_tables.sql (que si hace drop) y luego 002.

begin;

-- ---------------------------------------------------------------------------
-- 1. patient
-- ---------------------------------------------------------------------------

create table if not exists patient (
    patient_id    serial       primary key,
    patient_code  varchar(16)  not null unique,
    first_name    varchar(80),
    last_name     varchar(80),
    national_id   varchar(16)  unique,
    created_at    timestamptz  not null default now(),

    constraint patient_national_id_format
        check (national_id is null or national_id ~ '^[0-9]{8}$'),

    constraint patient_code_format
        check (patient_code ~ '^[A-Za-z0-9_-]{1,16}$')
);

comment on table  patient              is 'Paciente al que pertenece un estudio.';
comment on column patient.patient_code is 'Codigo interno del paciente. Obligatorio.';
comment on column patient.first_name   is 'Nombre. Opcional.';
comment on column patient.last_name    is 'Apellido. Opcional.';
comment on column patient.national_id  is 'DNI. Opcional y unico cuando se registra.';


-- ---------------------------------------------------------------------------
-- 2. organ
-- ---------------------------------------------------------------------------

create table if not exists organ (
    organ_id          serial       primary key,
    name              varchar(32)  not null unique,
    anatomical_region varchar(64)  not null,

    constraint organ_name_allowed
        check (name in ('lung', 'liver'))
);

comment on table  organ                   is 'Organo sobre el que se hace un estudio.';
comment on column organ.name              is 'lung o liver. Alcance vigente: dos organos.';
comment on column organ.anatomical_region is 'Region anatomica que cubre el estudio.';


-- ---------------------------------------------------------------------------
-- 3. model
-- ---------------------------------------------------------------------------
-- Los pesos no se guardan aqui: viven en el bucket radvol3d-models.

create table if not exists model (
    model_id    serial       primary key,
    model_name  varchar(64)  not null,
    version     varchar(32)  not null,
    trained_on  date,
    description text,
    created_at  timestamptz  not null default now(),

    constraint model_name_version_unique unique (model_name, version)
);

comment on table  model             is 'Catalogo de modelos. Una fila por version.';
comment on column model.model_name  is 'Nombre de la estrategia que corrio.';
comment on column model.version     is 'Version del modelo. Con el nombre, identifica la fila.';
comment on column model.trained_on  is 'Fecha de entrenamiento. Dato real, no estimado.';


-- ---------------------------------------------------------------------------
-- 4. study
-- ---------------------------------------------------------------------------

create table if not exists study (
    study_id       serial       primary key,
    study_code     varchar(64)  not null unique,
    patient_id     integer      not null references patient(patient_id),
    organ_id       integer      not null references organ(organ_id),
    model_id       integer      references model(model_id),
    status         varchar(16)  not null default 'pending',
    grid_size      smallint,
    total_time_sec numeric(9, 3),
    created_at     timestamptz  not null default now(),

    constraint study_code_format
        check (study_code ~ '^[A-Za-z0-9_-]{1,64}$'),

    constraint study_status_allowed
        check (status in ('pending', 'processing', 'completed', 'failed')),

    constraint study_total_time_positive
        check (total_time_sec is null or total_time_sec >= 0)
);

comment on table  study                is 'Un estudio: un organo de un paciente, procesado una vez.';
comment on column study.study_code     is 'Identificador que usa la interfaz. Letras, digitos, guion y guion bajo.';
comment on column study.model_id       is 'Modelo de reconstruccion usado. Nulo mientras no se procesa.';
comment on column study.status         is 'pending, processing, completed o failed.';
comment on column study.grid_size      is 'Lado del volumen reconstruido, en voxeles.';
comment on column study.total_time_sec is 'Tiempo total del procesamiento, en segundos.';


-- ---------------------------------------------------------------------------
-- 5. projection
-- ---------------------------------------------------------------------------

create table if not exists projection (
    projection_id serial       primary key,
    study_id      integer      not null references study(study_id) on delete cascade,
    angle_degrees smallint     not null,
    file_path     text         not null,
    original_name varchar(255),

    constraint projection_angle_allowed
        check (angle_degrees in (0, 45, 90, 135)),

    constraint projection_study_angle_unique unique (study_id, angle_degrees)
);

comment on table  projection               is 'Las cuatro proyecciones de entrada de un estudio.';
comment on column projection.angle_degrees is 'Angulo de la proyeccion: 0, 45, 90 o 135.';
comment on column projection.file_path     is 'Ruta del .npy dentro del bucket de Storage.';
comment on column projection.original_name is 'Nombre del archivo que subio el usuario.';


-- ---------------------------------------------------------------------------
-- 6. processing_stage
-- ---------------------------------------------------------------------------

create table if not exists processing_stage (
    stage_id     serial       primary key,
    study_id     integer      not null references study(study_id) on delete cascade,
    stage_number smallint     not null,
    stage_name   varchar(32)  not null,
    stage_status varchar(16)  not null default 'waiting',
    model_id     integer      references model(model_id),
    started_at   timestamptz,
    finished_at  timestamptz,

    constraint stage_number_allowed
        check (stage_number between 1 and 4),

    constraint stage_status_allowed
        check (stage_status in ('waiting', 'running', 'completed', 'skipped', 'failed')),

    constraint stage_study_number_unique unique (study_id, stage_number)
);

comment on table  processing_stage              is 'Las cuatro etapas de la tuberia por estudio.';
comment on column processing_stage.stage_number is '1 preprocesamiento, 2 reconstruccion, 3 segmentacion, 4 mallas.';
comment on column processing_stage.stage_status is 'waiting, running, completed, skipped o failed.';
comment on column processing_stage.model_id     is 'Modelo que ejecuto esta etapa, cuando corresponde.';


-- ---------------------------------------------------------------------------
-- 7. lesion (ya incluye la columna organ de la migracion 002)
-- ---------------------------------------------------------------------------

create table if not exists lesion (
    lesion_id       serial         primary key,
    study_id        integer        not null references study(study_id) on delete cascade,
    location        varchar(128)   not null,
    volume_mm3      numeric(12, 2) not null,
    max_diameter_mm numeric(8, 2),
    confidence      numeric(5, 4)  not null,
    mesh_path       text,
    created_at      timestamptz    not null default now(),
    organ           varchar(32)    not null,

    constraint lesion_volume_positive
        check (volume_mm3 > 0),

    constraint lesion_confidence_range
        check (confidence >= 0 and confidence <= 1),

    constraint lesion_organ_allowed
        check (organ in ('lung', 'liver'))
);

comment on table  lesion                 is 'Regiones marcadas como lesion por el segmentador.';
comment on column lesion.location        is 'Posicion geometrica dentro del volumen. No es un lobulo anatomico.';
comment on column lesion.volume_mm3      is 'Volumen de la lesion en milimetros cubicos.';
comment on column lesion.max_diameter_mm is 'Diametro maximo. Opcional: el segmentador puede no entregarlo.';
comment on column lesion.confidence      is 'Confianza media de la region, entre 0 y 1.';
comment on column lesion.mesh_path       is 'Ruta del .glb de la lesion dentro del bucket.';
comment on column lesion.organ           is 'Órgano al que pertenece la lesión: lung o liver.';


-- ---------------------------------------------------------------------------
-- 8. Indices
-- ---------------------------------------------------------------------------

create index if not exists idx_study_patient          on study(patient_id);
create index if not exists idx_study_organ            on study(organ_id);
create index if not exists idx_study_model            on study(model_id);
create index if not exists idx_study_status           on study(status);
create index if not exists idx_projection_study       on projection(study_id);
create index if not exists idx_processing_stage_study on processing_stage(study_id);
create index if not exists idx_lesion_study           on lesion(study_id);


-- ---------------------------------------------------------------------------
-- 9. Seguridad a nivel de fila
-- ---------------------------------------------------------------------------
-- Sin politicas: solo la clave de servicio (la que usa la aplicacion) entra.

alter table patient          enable row level security;
alter table organ            enable row level security;
alter table model            enable row level security;
alter table study            enable row level security;
alter table projection       enable row level security;
alter table processing_stage enable row level security;
alter table lesion           enable row level security;


-- ---------------------------------------------------------------------------
-- 10. Datos iniciales
-- ---------------------------------------------------------------------------

insert into patient (patient_code, first_name, last_name, national_id)
values ('PAC000000', null, null, null)
on conflict (patient_code) do nothing;

insert into organ (name, anatomical_region) values
    ('lung',  'thorax'),
    ('liver', 'upper abdomen')
on conflict (name) do nothing;


-- ---------------------------------------------------------------------------
-- 11. Buckets de Storage (privados)
-- ---------------------------------------------------------------------------
-- radvol3d        -> STORAGE_BUCKET: proyecciones, volumenes, mascaras y mallas.
-- radvol3d-models -> MODEL_BUCKET: pesos .pth de los modelos.
-- Los archivos no se copian con SQL: los pesos hay que subirlos a mano y las
-- rutas deben coincidir con EN1_WEIGHTS_OBJECT y EN2_WEIGHTS_OBJECT del .env.

insert into storage.buckets (id, name, public) values
    ('radvol3d',        'radvol3d',        false),
    ('radvol3d-models', 'radvol3d-models', false)
on conflict (id) do nothing;

commit;


-- ---------------------------------------------------------------------------
-- 12. Verificacion
-- ---------------------------------------------------------------------------
-- En un proyecto nuevo: patient 1, organ 2 y el resto en 0.

select 'patient'          as table_name, count(*) as rows from patient
union all select 'organ',            count(*) from organ
union all select 'model',            count(*) from model
union all select 'study',            count(*) from study
union all select 'projection',       count(*) from projection
union all select 'processing_stage', count(*) from processing_stage
union all select 'lesion',           count(*) from lesion
order by table_name;
