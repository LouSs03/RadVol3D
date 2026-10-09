"""Las cuatro etapas encadenadas.

Recibe sus estrategias ya construidas y no sabe cual le toco. Eso es lo que
permite probar la tuberia completa con dobles, sin GPU ni modelo.
"""

from radvol3d.domain.entities import Study
from radvol3d.services.meshing.meshing_strategy import MeshingStrategy
from radvol3d.services.pipeline.projection_loader import ProjectionLoader
from radvol3d.services.reconstruction.reconstruction_strategy import ReconstructionStrategy
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy


class ProcessingPipeline:
    """Encadena preprocesamiento, reconstruccion, segmentacion y mallas."""

    def __init__(
        self,
        loader: ProjectionLoader,
        reconstruction: ReconstructionStrategy,
        segmentation: SegmentationStrategy,
        meshing: MeshingStrategy,
    ) -> None:
        self._loader = loader
        self._reconstruction = reconstruction
        self._segmentation = segmentation
        self._meshing = meshing

    def run(self, study_code: str, files: list[bytes]) -> Study:
        """Procesa un estudio completo y devuelve su estado final."""
        raise NotImplementedError("TODO: encadenar las cuatro etapas y registrarlas")
