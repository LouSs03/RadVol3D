# Arquitectura en capas

Capas cerradas: cada una llama solo a la inmediata inferior. `domain` no es una
capa mas sino un piso de tipos compartidos, sin logica ni entrada y salida, que
todas pueden importar.

| Capa | Carpeta | Que hace | Solo puede importar |
|---|---|---|---|
| 0 Dominio | `domain/` | entidades, enumerados y errores | nada del proyecto |
| 1 Presentacion | `api/`, `web/` | recibe peticiones y devuelve respuestas | `services`, `domain`, `config` |
| 2 Logica | `services/` | reconstruye, segmenta y genera mallas | `persistence`, `domain`, `config` |
| 3 Persistencia | `persistence/` | guarda y lee en PostgreSQL y Storage | `domain`, `config` |
| 4 Datos | Supabase | tablas y bucket | no es codigo |

## Las dos reglas que se verifican solas

1. **La persistencia no sabe que existe una web.** No importa `fastapi` ni
   `starlette`. Si lo hiciera, cambiar de servidor obligaria a reescribir el
   acceso a datos.
2. **La presentacion no sabe que existe una base de datos.** No importa
   `persistence` ni `psycopg`. Si lo hiciera, un cambio de columna llegaria
   hasta el HTML.

`tests/architecture/test_layer_boundaries.py` las comprueba en cada push. Si
falla, se corrige el import, nunca la prueba.

## Por que existe domain/

Cuando la capa 3 devuelve un estudio y la capa 2 lo pasa a la capa 1, las tres
necesitan el mismo tipo de dato. Si eso viaja como diccionario suelto, cada capa
supone que claves trae y el error aparece en la demostracion. Con una dataclass
compartida, aparece al escribir el codigo.

## Equivalencias con el repositorio anterior

TODO: completar a medida que se migre cada archivo.

| Archivo anterior | Archivo nuevo |
|---|---|
| `servicio/persistencia/layout.py` | `persistence/storage_layout.py` |
| `servicio/persistencia/storage.py` | `persistence/object_storage.py` |
| `servicio/persistencia/almacen_archivos.py` | desaparece: ya no hace falta |
