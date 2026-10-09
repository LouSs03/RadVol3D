"""Extrae las superficies con marching cubes y las exporta en GLB."""

from typing import Any

from radvol3d.services.meshing.meshing_strategy import MeshingStrategy, MeshSet


class MarchingCubesStrategy(MeshingStrategy):
    """Genera la malla del organo y la del tumor con marching cubes."""

    def build_meshes(self, volume: Any, mask: Any) -> MeshSet:
        raise NotImplementedError("TODO: marching cubes y exportacion a GLB (T082)")
