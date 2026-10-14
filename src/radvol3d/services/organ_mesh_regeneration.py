"""Vuelve a generar la malla del organo de estudios ya procesados.

Cuando cambia la region del organo (el pulmon paso de la region de tejido a
LungAirRegion, docs/models/meshing.md), los estudios procesados antes conservan la malla
vieja. El volumen reconstruido esta guardado, asi que la malla se rehace sin volver a
correr EN-1 ni EN-2.

Solo cambia organ.glb. El tumor, las lesiones, sus filas y el resumen quedan como
estan: las lesiones descartadas al procesar no se vuelven a decidir, porque eso
desalinearia el resultado guardado con la base.

La estrategia de mallas sale de la fabrica (StrategyFactory.meshing_for), como al
procesar: no hay condicionales por organo aqui.
"""

import io
from dataclasses import dataclass

import numpy as np

from radvol3d.domain.entities import Study
from radvol3d.domain.enums import OrganName, ResultFile, StudyStatus
from radvol3d.persistence.result_store import ResultStore
from radvol3d.persistence.study_metadata_store import StudyMetadataStore
from radvol3d.services.strategy_factory import StrategyFactory


@dataclass(frozen=True)
class OrganMeshUpdate:
    """La malla del organo de un estudio, antes y despues de regenerarla."""

    study_code: str
    organ: OrganName
    previous: bytes
    current: bytes


class OrganMeshRegenerator:
    """Rehace la malla del organo desde el volumen guardado y la guarda."""

    def __init__(
        self,
        metadata_store: StudyMetadataStore,
        result_store: ResultStore,
        factory: StrategyFactory,
    ) -> None:
        self._metadata_store = metadata_store
        self._result_store = result_store
        self._factory = factory

    def completed_studies(self) -> list[Study]:
        """Los estudios terminados, del mas reciente al mas antiguo."""
        return [
            study
            for study in self._metadata_store.list_studies()
            if study.status is StudyStatus.COMPLETED
        ]

    def build(self, study: Study) -> OrganMeshUpdate:
        """Calcula la malla nueva sin guardar nada."""
        volume = np.load(
            io.BytesIO(self._result_store.read_file(study.study_code, ResultFile.VOLUME)),
            allow_pickle=False,
        )
        previous = self._result_store.read_file(study.study_code, ResultFile.ORGAN_MESH)
        # Sin mascara ni regiones: de este llamado solo se usa la malla del organo.
        meshes = self._factory.meshing_for(study.organ).build_meshes(
            volume, np.zeros(volume.shape, dtype=np.uint8), []
        )
        return OrganMeshUpdate(study.study_code, study.organ, previous, meshes.organ)

    def save(self, study_code: str, organ_mesh: bytes) -> None:
        """Guarda la malla del organo del estudio (la nueva o, para deshacer, la vieja)."""
        self._result_store.replace_organ_mesh(study_code, organ_mesh)
