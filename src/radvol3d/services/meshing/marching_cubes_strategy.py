"""Extrae la superficie con marching cubes y la exporta en GLB."""

from typing import Any

from radvol3d.services.meshing.meshing_strategy import MeshingStrategy


class MarchingCubesStrategy(MeshingStrategy):
    """Genera la malla con marching cubes y la simplifica antes de exportar."""

    def build_mesh(self, mask: Any) -> bytes:
        raise NotImplementedError("TODO: marching cubes y exportacion a GLB")
