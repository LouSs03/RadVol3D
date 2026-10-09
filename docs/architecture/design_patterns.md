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

| Archivo | Papel |
|---|---|
| `services/reconstruction/reconstruction_strategy.py` | la interfaz |
| `services/reconstruction/backprojection_strategy.py` | estrategia concreta |
| `services/reconstruction/neural_en1_strategy.py` | estrategia concreta |
| `services/segmentation/segmentation_strategy.py` | la interfaz |
| `services/segmentation/lung_unet_strategy.py` | estrategia concreta |
| `services/segmentation/liver_unet_strategy.py` | estrategia concreta |
| `services/processing_pipeline.py` | el contexto que las usa |

## Patrones secundarios

| Patron | Donde | Para que |
|---|---|---|
| Factory Method | `services/strategy_factory.py` | un solo lugar sabe que estrategia corresponde a cada organo |
| Repository | `persistence/repositories/` | aisla el acceso a datos del resto del sistema |
| Pipes and Filters | `services/processing_pipeline.py` | las cuatro etapas encadenadas, las mismas de `processing_stage` |
