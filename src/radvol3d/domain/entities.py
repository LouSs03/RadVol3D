"""Entidades del dominio.

Son los tipos que viajan entre capas. Usar dataclasses en lugar de diccionarios
sueltos hace que un campo mal escrito falle al escribir el codigo y no durante
la demostracion.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from radvol3d.domain.enums import OrganName, StageNumber, StageStatus, StudyStatus


@dataclass(frozen=True)
class Patient:
    """Persona a la que pertenece un estudio.

    Los datos personales se excluyen de la representacion en texto para que un
    registro o una traza no los muestre.
    """

    patient_code: str
    first_name: str | None = field(default=None, repr=False)
    last_name: str | None = field(default=None, repr=False)
    national_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class PatientDetails:
    """Datos personales que llegan de la interfaz. Los tres son opcionales."""

    first_name: str | None = field(default=None, repr=False)
    last_name: str | None = field(default=None, repr=False)
    national_id: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class Model:
    """Una version de un modelo. Con su nombre, identifica una fila del catalogo."""

    model_name: str
    version: str
    trained_on: date | None = None
    description: str | None = None


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
    model: Model | None = None


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
    patient: Patient | None = None
    model: Model | None = None
    grid_size: int | None = None


@dataclass(frozen=True)
class StoredResult:
    """Resultado guardado de un estudio: sus lesiones y las rutas de sus archivos.

    Un estudio que todavia no tiene resultado se representa con las cinco rutas en
    None y la lista de lesiones vacia.
    """

    study_code: str
    lesions: list[Lesion] = field(default_factory=list)
    mask_path: str | None = None
    probability_path: str | None = None
    summary_path: str | None = None
    organ_mesh_path: str | None = None
    tumor_mesh_path: str | None = None


@dataclass
class SegmentationResult:
    """Lo que devuelve una estrategia de segmentacion.

    mask y probability son arreglos de numpy de la misma forma. No se declaran con
    su tipo para que esta capa no dependa de numpy. summary es el resumen por region
    que se guarda como summary.json; cada region con lesion tambien esta en lesions.
    """

    mask: object
    probability: object
    global_confidence: float
    lesions: list[Lesion] = field(default_factory=list)
    summary: Mapping[str, object] = field(default_factory=dict)
