"""Constantes del sistema. No lee el entorno: eso es tarea de la capa 3."""

from typing import Final

# Lado de la rejilla del volumen reconstruido, en voxeles.
# Justificado en docs/decisions/0003_grid_128.md (Loyen et al., 2023).
GRID_SIZE: Final[int] = 128

# Campo de vision fisico que cubre la rejilla, en milimetros.
FIELD_OF_VIEW_MM: Final[float] = 320.0

# Tamano del voxel. Debe coincidir con el del conjunto de entrenamiento.
MM_PER_VOXEL: Final[float] = FIELD_OF_VIEW_MM / GRID_SIZE

# Angulos de las cuatro proyecciones de entrada, en grados.
PROJECTION_ANGLES: Final[tuple[int, ...]] = (0, 45, 90, 135)

# Ventana de unidades Hounsfield con la que se normaliza a [0, 1].
HU_WINDOW: Final[tuple[float, float]] = (-1000.0, 1000.0)

# Formatos aceptados al subir una proyeccion: solo .npy en el convenio de TA-2.
# PNG no tiene la escala que espera EN-1 (integrales de linea sin normalizar).
ACCEPTED_FORMATS: Final[tuple[str, ...]] = (".npy",)

# Tamano maximo de cada archivo de proyeccion que se sube, en bytes: 1 MiB.
# Un .npy de 128 x 128 pesa 65 664 bytes en float32 y 131 200 en float64, asi que el
# limite deja margen sin aceptar archivos absurdos (research.md R7 de la funcionalidad 004).
MAX_PROJECTION_BYTES: Final[int] = 1_048_576
