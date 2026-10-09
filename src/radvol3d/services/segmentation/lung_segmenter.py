"""Segmentador de tumor de pulmon EN-2.

Usa PyTorch, pero lo importa dentro de cada metodo y no al importar el modulo: asi la
coleccion de pytest no falla donde torch no esta instalado, como en el CI.

Migrado desde models/en2_inferencia.py (research.md R14). La logica de carga y de
inferencia no cambia: mismas claves del archivo de pesos, mismos valores por omision,
mismo TTA, mismas ventanas, mismos pesos gaussianos y mismo umbral. Solo cambian dos
cosas, y ninguna altera la salida numerica:

- los pesos se leen con torch.load(..., weights_only=True): vienen de un bucket
  remoto y weights_only=False ejecutaria cualquier objeto serializado (R15);
- el dispositivo por omision es "cpu" (el servidor no tiene GPU).

Las claves del archivo de pesos (pesos, umbral, parche, ...) siguen en espanol porque
son el formato del archivo. No se migran la autoprueba ni la linea de comandos: las
reemplazan las pruebas "ml".

Contrato de entrada: arreglo 3D cubico float32 en [0, 1], normalizado con la misma
ventana de Hounsfield que TA-1 y EN-1 (-1000 a 1000 HU): el volumen que devuelve el
reconstructor.
"""

import numpy as np

from radvol3d.services.segmentation.lung_region_summary import (
    InvalidVolumeError,
    clean_mask,
    gaussian_weight_map,
    patch_positions,
    summarize_regions,
)


class LungSegmenter:
    """Segmenta el tumor sobre un volumen reconstruido: mascara, confianza y resumen."""

    def __init__(self, weights_path, device="cpu"):
        import torch

        from radvol3d.services.segmentation.lung_unet_network import SegmentationUnet3d

        data = torch.load(weights_path, map_location="cpu", weights_only=True)
        if "pesos" not in data:
            raise ValueError(
                f"El archivo no tiene la clave 'pesos'. Claves presentes: {sorted(data)[:10]}"
            )
        self.device = torch.device(device)
        self.channels = tuple(data["canales"])
        self.threshold = float(data["umbral"])
        self.min_voxels = int(data.get("min_voxeles", 0))
        self.patch = int(data["parche"])
        self.overlap = float(data.get("solape", 0.5))
        self.tta = bool(data.get("tta", True))
        self.grid = int(data["rejilla"])
        self.mm_per_voxel = float(data["mm_por_voxel"])
        self.hu_window = list(data.get("ventana_hu", [-1000.0, 1000.0]))
        self.organ = data.get("organo", "pulmon")
        self.model_name = data.get("nombre_modelo", "segmentacion_pulmon")
        self.version = data.get("version", "1.0.0")
        self.metrics = data.get("metricas", {})

        self.model = SegmentationUnet3d(
            channels=self.channels, supervision=int(data.get("supervision", 3))
        )
        self.model.load_state_dict(data["pesos"], strict=True)
        self.model.to(self.device).eval()
        self._weight = gaussian_weight_map(self.patch)

    def describe(self):
        return {
            "model": self.model_name,
            "version": self.version,
            "organ": self.organ,
            "threshold": self.threshold,
            "grid": self.grid,
            "mm_per_voxel": self.mm_per_voxel,
            "hu_window": self.hu_window,
            "channels": list(self.channels),
            "device": str(self.device),
            "metrics": self.metrics,
        }

    def _validate(self, volume):
        v = np.asarray(volume)
        if v.ndim != 3:
            raise InvalidVolumeError(f"Se esperaba un arreglo 3D, llego {v.ndim}D")
        if len(set(v.shape)) != 1:
            raise InvalidVolumeError(f"Se esperaba un volumen cubico, llego {v.shape}")
        v = v.astype(np.float32)
        if float(v.min()) < -0.01 or float(v.max()) > 1.01:
            raise InvalidVolumeError(
                f"El volumen debe venir normalizado a [0,1] con la ventana HU {self.hu_window}; "
                f"llego el rango [{v.min():.3f}, {v.max():.3f}]"
            )
        return np.clip(v, 0.0, 1.0)

    def probability(self, volume):
        """Probabilidad de tumor por voxel: float32 en [0, 1], misma forma que la entrada."""
        import torch

        with torch.no_grad():
            return self._probability(volume)

    def _probability(self, volume):
        """Cuerpo de probability; se llama dentro de torch.no_grad()."""
        import torch

        v = self._validate(volume)
        p = self.patch
        original_shape = v.shape
        # Si el volumen es menor que el parche se rellena con aire (0) y se recorta al
        # final. Asi el modulo acepta tambien rejillas de 64 sin fallar.
        padding = [(0, max(p - s, 0)) for s in v.shape]
        if any(b for _, b in padding):
            v = np.pad(v, padding, mode="constant", constant_values=0.0)
        accumulated = np.zeros(v.shape, np.float32)
        weight = np.zeros(v.shape, np.float32)
        flips = (
            [(), (2,), (3,), (4,), (2, 3), (2, 4), (3, 4), (2, 3, 4)] if self.tta else [()]
        )
        positions = [patch_positions(s, p, self.overlap) for s in v.shape]
        for z in positions[0]:
            for y in positions[1]:
                for x in positions[2]:
                    t = torch.from_numpy(v[z : z + p, y : y + p, x : x + p][None, None]).to(
                        self.device
                    )
                    total = torch.zeros_like(t)
                    for axes in flips:
                        e = torch.flip(t, axes) if axes else t
                        s = torch.sigmoid(self.model(e)[0].float())
                        total += torch.flip(s, axes) if axes else s
                    patch_probability = (total / len(flips))[0, 0].cpu().numpy()
                    accumulated[z : z + p, y : y + p, x : x + p] += patch_probability * self._weight
                    weight[z : z + p, y : y + p, x : x + p] += self._weight
        result = np.clip(accumulated / np.maximum(weight, 1e-6), 0.0, 1.0).astype(np.float32)
        d, h, w = original_shape
        return result[:d, :h, :w]

    def segment(self, volume, study_id=None):
        """Devuelve mascara, confianza por voxel y resumen agregado por region."""
        probability = self.probability(volume)
        mask = clean_mask(probability >= self.threshold, self.min_voxels)
        regions = summarize_regions(mask, probability, self.mm_per_voxel, self.min_voxels)

        if regions:
            weights = np.array([r["volume_mm3"] for r in regions], dtype=np.float64)
            confidence = float(np.average([r["confidence"] for r in regions], weights=weights))
        else:
            # Sin lesion: la confianza es la de que NO hay nada que marcar.
            confidence = float(1.0 - probability.max())

        summary = {
            "study_id": study_id,
            "organ": self.organ,
            "model_name": self.model_name,
            "model_version": self.version,
            "threshold": self.threshold,
            "mm_per_voxel": self.mm_per_voxel,
            "grid": int(mask.shape[0]),
            "has_lesion": bool(regions),
            "lesion_count": len(regions),
            "global_confidence": round(confidence, 4),
            "total_volume_mm3": round(sum(r["volume_mm3"] for r in regions), 2),
            "regions": regions,
            "location_note": (
                "posicion geometrica dentro del volumen; "
                "no es una identificacion de lobulo anatomico"
            ),
        }
        return {"mask": mask, "probability": probability, "summary": summary}
