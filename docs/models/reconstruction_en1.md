# Modelo de reconstrucción EN-1

| | |
|---|---|
| Entrada | `(4, 128, 128)` float32: integrales de línea del convenio de TA-2, sin normalizar, a 0, 45, 90 y 135 grados |
| Salida | `(128, 128, 128)` float32 en [0, 1], ventana HU de -1000 a 1000 |
| Arquitectura | retroproyector de TA-2 con filtro rampa (exponente 0,5) y dos calibraciones afines, más U-Net 3D residual de cuatro reducciones |
| Parámetros | 5 885 937 (medido con la autoprueba original) |
| Registro en `model` | `reconstruction_en1`, versión `1.0.0` |
| Fecha de entrenamiento | `TODO(TRAINING_DATE_EN1)`: no está en los pesos ni en el repositorio; `trained_on` queda vacío |

## Dónde vive cada cosa

- **Código.**
  - `src/radvol3d/services/reconstruction/en1_geometry.py`: operadores y constantes, solo numpy y scipy.
  - `en1_network.py`: la red.
  - `en1_reconstructor.py`: carga e inferencia.
  - `neural_en1_strategy.py`: la estrategia.

  Todo se migró de `models/en1_inferencia_nuevo (1).py` sin cambiar la lógica. Los
  atributos de la red que forman las claves del `state_dict` conservan su nombre original.
- **Pesos.** Bucket de modelos, `reconstruction_en1/1.0.0/weights.pth`. Es una copia sin
  cambios de `models/en1_pesos_liviano (2).pth`. El archivo trae solo `mejores_pesos`, así
  que la rejilla, el filtro y las calibraciones salen de las constantes del módulo.
- **Carga.** `torch.load(..., weights_only=True)`. El original usaba `weights_only=False`.
  Los tensores que se leen son los mismos.

## Entrada: qué no es

No son radiografías clínicas crudas. Una radiografía real trae la escala, el offset y la
respuesta del detector de su equipo. Convertirla al convenio de TA-2 es un paso de
calibración que el proyecto todavía no aborda. Por eso el sistema acepta solo `.npy` y no
reescala la entrada.

## Tiempo

En la laptop de desarrollo, en CPU, la autoprueba original tardó ≈ 11 s por estudio
(2026-10-09). Es una medición de referencia, no una meta.

## Regresión

`tests/ml/test_en1_regression.py` compara la salida migrada con la referencia que genera
`scripts/generate_regression_reference.py` con el script original. El caso es el fantoma
elipsoide de su autoprueba, y la tolerancia es `1e-5`.

## Resolución

La rejilla de 128 está justificada en `docs/decisions/0003_grid_128.md`.
