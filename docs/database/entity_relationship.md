# Modelo entidad-relacion

TODO: insertar el diagrama y explicar cada relacion.

## Decisiones discutidas

### Por que `organ` es una tabla y no una restriccion de tipo check

Solo hay dos organos, asi que una restriccion `check` bastaria hoy. Se mantuvo
como tabla por la relacion de un organo con muchos estudios, pensando en estudios
longitudinales del mismo organo a lo largo del tiempo.

TODO: confirmar si el alcance incluye estudios longitudinales.

### Por que `model` lleva version

Al mejorar un modelo hay que poder decir con cual se proceso cada estudio. La
restriccion de unicidad sobre `(model_name, version)` hace que el catalogo tenga
una fila por version y que muchos estudios apunten a la misma.

### Por que `lesion` guarda el organo como texto

Desde la migracion 002 (funcionalidad 004), cada lesion tiene la columna `organ` de texto
(`lung` o `liver`), aunque el organo ya cuelga del estudio por `organ_id`. Lo pidio la
especificacion. La repeticion no puede desalinearse: la aplicacion no recibe ese valor, lo
copia del estudio en el mismo `insert`, y `lesion_organ_allowed` limita los valores a los mismos
de `organ_name_allowed`.

### Por que `lesion` no guarda `region_id`

Cada lesion tiene su propia malla (`lesion_<NNN>.glb`), y el enlace entre la fila y su malla es
`mesh_path`. `region_id` solo vive en `summary.json`: la base no lo necesita.

### Que es `projection`

Las cuatro radiografias de entrada, en 0, 45, 90 y 135 grados. El modelo no las
genera: las recibe, reconstruye y segmenta.
