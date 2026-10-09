# Patrones de software

## Patron principal: Strategy

**Strategy** (Gamma, Helm, Johnson y Vlissides, 1994). Define una familia de
algoritmos, encapsula cada uno y los hace intercambiables, de modo que el
algoritmo varie sin que cambie quien lo usa.

### Por que este

El proyecto ya tiene, por necesidad, cuatro algoritmos intercambiables:

| Etapa | Algoritmos | Que los distingue |
|---|---|---|
| Reconstruccion | retroproyeccion simple, modelo EN-1 | linea base frente a red neuronal |
| Segmentacion | modelo de pulmon, modelo de higado | un modelo entrenado por organo |

Todos los de una etapa reciben y devuelven lo mismo. Esa igualdad de firma es la
definicion del patron.

Cuatro razones concretas:

1. **La base de datos ya lo presupone.** La tabla `model` guarda `model_name` y
   `version` por estudio: eso es registrar que estrategia corrio.
2. **Ataca la brecha 1 del estado del arte.** Ningun modelo publicado opera sobre
   mas de una region anatomica. Strategy es la respuesta de diseno: una sola
   tuberia sirve a pulmon y a higado, y agregar un tercer organo es agregar un
   archivo.
3. **Evita el if repartido.** Sin el patron aparece `if organ == ...` en la
   tuberia, en el servicio y en la generacion de mallas.
4. **Hace posible la exigencia de pruebas unitarias.** Sin Strategy, probar la
   tuberia exige GPU, PyTorch y 24 MB de pesos. Con Strategy se inyecta un doble
   y la prueba corre en milisegundos. Ver `tests/fixtures/fake_strategies.py`.

### Donde esta

Hay una interfaz por etapa variable: reconstrucción, segmentación y mallas.

| Archivo | Papel |
|---|---|
| `services/reconstruction/reconstruction_strategy.py` | la interfaz |
| `services/reconstruction/neural_en1_strategy.py` | estrategia concreta: EN-1 |
| `services/reconstruction/backprojection_strategy.py` | esqueleto, fuera de la fábrica |
| `services/segmentation/segmentation_strategy.py` | la interfaz |
| `services/segmentation/lung_unet_strategy.py` | estrategia concreta: EN-2 de pulmón |
| `services/segmentation/liver_unet_strategy.py` | esqueleto; no hay modelo de hígado todavía |
| `services/meshing/meshing_strategy.py` | la interfaz |
| `services/meshing/marching_cubes_strategy.py` | estrategia concreta: marching cubes y `.glb` |
| `services/pipeline/processing_pipeline.py` | el contexto que las usa |

Las estrategias reales envuelven el código migrado de `models/`: las piezas sin torch
están en `en1_geometry.py` y `lung_region_summary.py`, y las que usan torch se importan
solo al construir la estrategia. Los dobles de `tests/fixtures/fake_strategies.py`
cumplen las mismas interfaces.

## Patrones secundarios

| Patron | Donde | Para que |
|---|---|---|
| Factory Method | `services/strategy_factory.py` | un solo lugar sabe que estrategia corresponde a cada organo. Recibe constructores y los llama una vez al arrancar (`preload`); un modelo que no carga queda no disponible sin detener el arranque |
| Repository | `persistence/repositories/` | aisla el acceso a datos del resto del sistema |
| Pipes and Filters | `services/pipeline/` | las cuatro etapas encadenadas (`filters.py`), las mismas de `processing_stage`. La tuberia registra cada etapa por el puerto `PipelineProgress` sin saber si del otro lado hay una base real o un doble |
