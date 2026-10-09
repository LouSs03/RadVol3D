# Modelo de reconstruccion EN-1

TODO: completar con los datos de la corrida de entrenamiento.

| | |
|---|---|
| Entrada | `(4, 128, 128)` float32 en [0,1], ventana HU de -1000 a 1000 |
| Salida | `(128, 128, 128)` float32 en [0,1] |
| Arquitectura | retroproyector de TA-2 con filtro rampa, mas U-Net 3D residual |
| Parametros | 5,89 M |
| Pesos | Supabase Storage, `modelos/reconstruccion_v1.pth` |

Los pesos no estan en el repositorio. La tabla `model` registra que version
proceso cada estudio.

## Resolucion

La rejilla de 128 esta justificada en `docs/decisions/0003_grid_128.md`.
