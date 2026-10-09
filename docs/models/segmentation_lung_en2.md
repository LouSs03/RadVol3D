# Modelo de segmentacion de pulmon EN-2

TODO: completar con las metricas de la corrida de entrenamiento.

| | |
|---|---|
| Entrada | `(128, 128, 128)` float32 en [0,1], misma ventana HU que la reconstruccion |
| Salida | mascara uint8, probabilidad float32 en [0,1], resumen por region |
| Arquitectura | U-Net 3D residual con supervision profunda |
| Conjunto | Medical Segmentation Decathlon, Task06_Lung |
| Pesos | Supabase Storage |

## Referencia de comparacion

Carles, M., Kuhn, D., Fechter, T., et al. (2024). Development and evaluation of
two open-source nnU-Net models for automatic segmentation of lung tumors on PET
and CT images. *European Radiology*, 34(10), 6701-6711.
DOI: 10.1007/s00330-024-10751-2

Dice de referencia: 0,63 +/- 0,34 sobre tomografia computarizada real.

## Diferencias de protocolo que hay que declarar

La referencia usa tomografia diagnostica a resolucion completa y entrenamiento
multicentrico. Aqui se trabaja sobre volumenes remuestreados a 2,5 mm por voxel y
con un conjunto de entrenamiento mucho menor.

Ademas, en el sistema el segmentador recibe un volumen **reconstruido**, no una
tomografia real. Medir cuanto cae el Dice en ese paso es la brecha 3 del estado
del arte y ningun trabajo revisado lo ha cuantificado.
