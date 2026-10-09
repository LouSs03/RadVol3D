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
