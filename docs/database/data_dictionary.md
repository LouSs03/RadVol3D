# Diccionario de datos

Una seccion por tabla. Para cada campo: nombre, tipo, si acepta nulos, que
significa y de donde sale.

TODO: completar con el esquema aplicado en Supabase.

## patient

| Campo | Tipo | Nulo | Descripcion |
|---|---|---|---|
| `patient_id` | serial | no | clave primaria |
| | | | TODO |

## organ

| Campo | Tipo | Nulo | Descripcion |
|---|---|---|---|
| `organ_id` | serial | no | clave primaria |
| `name` | varchar | no | `lung` o `liver` |
| | | | TODO |

## model

| Campo | Tipo | Nulo | Descripcion |
|---|---|---|---|
| `model_id` | serial | no | clave primaria |
| `model_name` | varchar | no | nombre de la estrategia que corrio |
| `version` | varchar | no | junto al nombre, identifica la fila |
| | | | TODO |

## study

TODO

## projection

TODO

## processing_stage

TODO

## lesion

TODO

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