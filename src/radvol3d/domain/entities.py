"""Entidades del dominio.

Son los tipos que viajan entre capas. Usar dataclasses en lugar de diccionarios
sueltos hace que un campo mal escrito falle al escribir el codigo y no durante
la demostracion.
"""

from dataclasses import dataclass, field
from datetime import datetime

from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus


@dataclass(frozen=True)
class Organ:
    """Organo sobre el que se hace un estudio."""

    organ_id: int
    name: OrganName
    anatomical_region: str


@dataclass(frozen=True)
class Projection:
    """Una de las cuatro radiografias de entrada."""

    angle_degrees: int
    file_path: str
    original_name: str | None = None


@dataclass(frozen=True)
class Lesion:
    """Region con lesion detectada por el segmentador.

    Los nombres coinciden con las columnas de la tabla lesion.
    """

    location: str
    volume_mm3: float
    confidence: float
    max_diameter_mm: float | None = None
    mesh_path: str | None = None


@dataclass(frozen=True)
class ProcessingStage:
    """Registro de una etapa ejecutada sobre un estudio."""

    stage_number: StageNumber
    status: StageStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class Study:
    """Un estudio completo, con sus proyecciones, etapas y lesiones."""

    study_code: str
    organ: OrganName
    status: StudyStatus
    created_at: datetime | None = None
    total_time_sec: float | None = None
    projections: list[Projection] = field(default_factory=list)
    stages: list[ProcessingStage] = field(default_factory=list)
    lesions: list[Lesion] = field(default_factory=list)


@dataclass
class SegmentationResult:
    """Lo que devuelve una estrategia de segmentacion.

    mask y probability son arreglos de numpy de la misma forma. No se declaran con
    su tipo para que esta capa no dependa de numpy.
    """

    mask: object
    probability: object
    global_confidence: float
    lesions: list[Lesion] = field(default_factory=list)
