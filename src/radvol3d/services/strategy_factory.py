"""Factory Method: un solo lugar sabe que estrategia corresponde a cada organo.

Sin esto, la decision se repartiria en if dispersos por la tuberia, el servicio y
la generacion de mallas, y cada organo nuevo obligaria a tocar los tres.
"""

from radvol3d.domain.enums import OrganName
from radvol3d.domain.exceptions import ModelNotAvailableError
from radvol3d.services.segmentation.liver_unet_strategy import LiverUnetStrategy
from radvol3d.services.segmentation.lung_unet_strategy import LungUnetStrategy
from radvol3d.services.segmentation.segmentation_strategy import SegmentationStrategy

SEGMENTATION_BY_ORGAN: dict[OrganName, type[SegmentationStrategy]] = {
    OrganName.LUNG: LungUnetStrategy,
    OrganName.LIVER: LiverUnetStrategy,
}


def build_segmentation_strategy(organ: OrganName, weights_path: str) -> SegmentationStrategy:
    """Devuelve la estrategia de segmentacion que corresponde al organo."""
    strategy_class = SEGMENTATION_BY_ORGAN.get(organ)
    if strategy_class is None:
        raise ModelNotAvailableError(f"No hay modelo de segmentacion para {organ.value}")
    return strategy_class(weights_path)
