-- Migracion 002 de RadVol3D: la tabla lesion guarda el organo como texto.
--
-- Funcionalidad 004 (specs/004-rest-api-viewer/research.md R11). Se aplica sobre
-- 001_create_tables.sql, en el editor SQL de Supabase: primero en la base de prueba y
-- despues en la real. No borra nada.
--
-- - organ es texto, no una clave foranea: lo pidio la especificacion. Repite el organo
--   del estudio; la comprobacion lesion_organ_allowed evita que se salga de los
--   organos permitidos, igual que organ_name_allowed en la tabla organ.
-- - La aplicacion no lo recibe del segmentador: LesionRepository lo toma del estudio
--   en el mismo insert.
-- - region_id sigue sin columna: el enlace entre cada fila y su malla es mesh_path,
--   que ahora apunta a <study_code>/meshes/lesion_<NNN>.glb.

begin;

alter table lesion add column organ varchar(32);

-- Las filas que ya existan toman el organo de su estudio.
update lesion l
set organ = o.name
from study s
join organ o on o.organ_id = s.organ_id
where s.study_id = l.study_id;

alter table lesion alter column organ set not null;

alter table lesion add constraint lesion_organ_allowed
    check (organ in ('lung', 'liver'));

comment on column lesion.organ is 'Órgano al que pertenece la lesión: lung o liver.';

commit;

-- Verificacion: una fila (organ, NO) y ninguna lesion sin organo.
--
-- select column_name, is_nullable from information_schema.columns
-- where table_name = 'lesion' and column_name = 'organ';
--
-- select count(*) from lesion where organ is null;
