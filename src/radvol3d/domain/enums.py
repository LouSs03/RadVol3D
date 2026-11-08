"""Valores cerrados del dominio.

Usar enumerados en lugar de cadenas sueltas evita el error mas comun entre capas:
que una escriba "completado" y otra espere "completed".
"""

from enum import Enum, StrEnum


class OrganName(StrEnum):
    """Organos que el sistema reconstruye. Alcance vigente: dos."""

    LUNG = "lung"
    LIVER = "liver"


class InputMode(StrEnum):
    """Como entra un estudio al sistema.

    - projections: las cuatro proyecciones sinteticas (.npy) de siempre.
    - radiograph: una sola radiografia de torax real (DICOM), reconstruida por el
      servicio externo AXON (guia del modo de una radiografia).
    """

    PROJECTIONS = "projections"
    RADIOGRAPH = "radiograph"


class RemoteJobState(StrEnum):
    """Estado de un trabajo en el servicio externo de reconstruccion, mientras dura.

    Solo se muestra al usuario ("en cola", "reconstruyendo"); no se guarda en la base.
    """

    QUEUED = "queued"
    RUNNING = "running"


class StudyStatus(StrEnum):
    """Estado de un estudio a lo largo de su procesamiento."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class StageNumber(int, Enum):
    """Las cuatro etapas de la tuberia. Son las cuatro filas de processing_stage."""

    PREPROCESSING = 1
    RECONSTRUCTION = 2
    SEGMENTATION = 3
    MESHING = 4


class StageStatus(StrEnum):
    """Estado de una etapa dentro de un estudio."""

    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ResultFile(StrEnum):
    """Archivos unicos de un resultado que se pueden descargar.

    Las mallas por lesion no estan aqui: se piden por su numero en la lista.
    """

    ORGAN_MESH = "organ_mesh"
    TUMOR_MESH = "tumor_mesh"
    VOLUME = "volume"
