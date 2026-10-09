"""Reconstructor EN-1: cuatro radiografias -> volumen de 128 x 128 x 128.

Usa PyTorch, pero lo importa dentro de cada metodo y no al importar el modulo: asi la
coleccion de pytest no falla donde torch no esta instalado, como en el CI.

Migrado desde models/en1_inferencia_nuevo (1).py (research.md R14). La logica de
reconstruccion no cambia. Solo cambian dos cosas, y ninguna altera la salida numerica:

- los pesos se leen con torch.load(..., weights_only=True): vienen de un bucket
  remoto y weights_only=False ejecutaria cualquier objeto serializado (R15);
- el dispositivo por omision es "cpu" (el servidor no tiene GPU).

No se migran reconstruir_lote, a_hu, de_hu, espaciado_mm, la autoprueba ni la linea de
comandos: la tuberia procesa un estudio por corrida y la autoprueba la reemplazan las
pruebas "ml".

Se instancia AL ARRANCAR, no en cada peticion: cargar los pesos cuesta mas que
reconstruir un caso.
"""

import os

import numpy as np

from radvol3d.services.reconstruction.en1_geometry import (
    ANGLES,
    BP_CALIBRATION,
    FBP_CALIBRATION,
    FILTER_EXPONENT,
    G,
    apply_affine,
    back_project,
    ramp_filter,
)


class En1Reconstructor:
    """Carga los pesos una sola vez y reconstruye tantos casos como se le pidan."""

    def __init__(self, weights_path, device="cpu"):
        import torch

        from radvol3d.services.reconstruction.en1_network import ResidualUnet3d

        if not os.path.exists(weights_path):
            raise FileNotFoundError("No existe el archivo de pesos de EN-1.")

        self.device = torch.device(device)
        data = torch.load(weights_path, map_location="cpu", weights_only=True)

        # El proyecto genero varios formatos y se aceptan todos. El ORDEN importa:
        # "mejores_pesos" son los de la epoca con mejor PSNR de validacion; "modelo" son
        # los de la epoca en que se guardo el archivo, que en un punto de control
        # intermedio NO es la mejor. Tomar "modelo" de un checkpoint de mitad de
        # entrenamiento carga un modelo peor sin avisar: reconstruye, no falla, y nadie
        # lo nota.
        if isinstance(data, dict) and data.get("mejores_pesos"):
            state, self.weights_source = data["mejores_pesos"], "mejores_pesos"
        elif isinstance(data, dict) and "pesos" in data:
            state, self.weights_source = data["pesos"], "pesos"
        elif isinstance(data, dict) and "modelo" in data:
            state, self.weights_source = data["modelo"], "modelo"
        elif isinstance(data, dict) and "state_dict" in data:
            state, self.weights_source = data["state_dict"], "state_dict"
        else:
            state, data, self.weights_source = data, {}, "archivo plano"

        self.channels = int(data.get("canales", 2))
        self.base = int(data.get("base", data.get("cfg", {}).get("base_canales", 16)))
        self.grid = int(data.get("rejilla", G))

        # Las constantes del archivo mandan sobre las del modulo.
        self.filter_exponent = float(data.get("exponente_filtro", FILTER_EXPONENT))
        self.fbp_calibration = tuple(data.get("calibracion_fbp", FBP_CALIBRATION))
        self.bp_calibration = tuple(data.get("calibracion_bp", BP_CALIBRATION))

        self.best_epoch = data.get("mejor_epoca", data.get("epoca"))
        self.validation_psnr = data.get(
            "psnr_validacion", data.get("mejor_psnr", data.get("psnr"))
        )

        self.model = ResidualUnet3d(self.channels, self.base).to(self.device)
        self.model.load_state_dict(state, strict=True)
        self.model.eval()
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def describe(self):
        return {
            "device": str(self.device),
            "grid": self.grid,
            "input_channels": self.channels,
            "base_channels": self.base,
            "parameters": sum(p.numel() for p in self.model.parameters()),
            "filter_exponent": self.filter_exponent,
            "fbp_calibration": list(self.fbp_calibration),
            "bp_calibration": list(self.bp_calibration),
            "best_epoch": self.best_epoch,
            "validation_psnr": self.validation_psnr,
            "weights_source": self.weights_source,
        }

    def prepare_input(self, projections):
        """(4, G, G) -> (1, 2, G, G, G) en el dispositivo.

        Canal 0: retroproyeccion FILTRADA y calibrada. Es tambien la base de la conexion
                 residual, asi que el modelo parte de ella.
        Canal 1: retroproyeccion SIMPLE y calibrada, como informacion adicional.

        El orden importa: invertirlo hace que el residual se sume sobre la
        reconstruccion peor y el resultado cae varios decibelios.
        """
        import torch

        p = np.asarray(projections, dtype=np.float32)
        if p.shape != (len(ANGLES), self.grid, self.grid):
            raise ValueError(
                f"Se esperaba ({len(ANGLES)}, {self.grid}, {self.grid}) y llego {p.shape}"
            )
        if not np.isfinite(p).all():
            raise ValueError("Las proyecciones contienen NaN o infinitos")

        fbp = apply_affine(
            back_project(ramp_filter(p, exponent=self.filter_exponent)), self.fbp_calibration
        )
        bp = apply_affine(back_project(p), self.bp_calibration)
        x = np.stack([fbp, bp])[None].astype(np.float32)
        return torch.from_numpy(x).to(self.device)

    def reconstruct(self, projections):
        """(4, G, G) -> volumen (G, G, G) float32 en [0, 1]."""
        import torch

        with torch.no_grad():
            x = self.prepare_input(projections)
            y = self.model(x).clamp(0.0, 1.0)
            return y[0, 0].float().cpu().numpy()

    def baseline(self, projections):
        """La FBP calibrada sola, sin modelo. Sirve para comprobar que el modelo aporta."""
        p = np.asarray(projections, dtype=np.float32)
        return apply_affine(
            back_project(ramp_filter(p, exponent=self.filter_exponent)), self.fbp_calibration
        )
