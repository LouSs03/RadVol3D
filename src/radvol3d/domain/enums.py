"""Valores cerrados del dominio.

Usar enumerados en lugar de cadenas sueltas evita el error mas comun entre capas:
que una escriba "completado" y otra espere "completed".
"""

from enum import Enum, StrEnum


class OrganName(StrEnum):
    """Organos que el sistema reconstruye. Alcance vigente: dos."""

    LUNG = "lung"
    LIVER = "liver"


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
