-- Migracion 003 de RadVol3D: modo de entrada de una radiografia.
--
-- Guia del modo de una radiografia (Lourdes, 7 de noviembre de 2026). Se aplica sobre
-- 002_add_lesion_organ.sql, en el editor SQL de Supabase: primero en la base de prueba
-- y despues en la real. No borra nada y los estudios que ya existen quedan como
-- 'projections', asi que el modo de cuatro proyecciones no cambia.
--
-- IMPORTANTE: aplicala ANTES de desplegar el codigo que la usa. El codigo nuevo lee
-- estas dos columnas en cada consulta de estudio.
--
-- - input_mode: como entro el estudio. 'projections' (las cuatro proyecciones .npy de
--   siempre) o 'radiograph' (un DICOM de torax que reconstruye el servicio AXON).
-- - radiograph_path: ruta del DICOM en el bucket (<study_code>/input/radiograph.dcm).
--   Solo la tienen los estudios 'radiograph', y solo despues de subirlo. No hace falta
--   una tabla aparte: un estudio tiene a lo sumo una radiografia.
-- - El trabajo del servicio externo (job_id) no se guarda: vive en la memoria del
--   servicio y se pierde si Colab se reinicia. Un estudio interrumpido queda failed
--   al arrancar, igual que uno de cuatro proyecciones, y se reintenta con uno nuevo.

begin;

alter table study add column input_mode varchar(16) not null default 'projections';

alter table study add constraint study_input_mode_allowed
    check (input_mode in ('projections', 'radiograph'));

alter table study add column radiograph_path text;

-- Solo un estudio de una radiografia puede tener radiografia.
alter table study add constraint study_radiograph_only_in_radiograph_mode
    check (radiograph_path is null or input_mode = 'radiograph');

commit;

-- Verificacion: todos los estudios existentes deben salir como 'projections'.
select input_mode, count(*) as studies from study group by input_mode;
