"""Arquitectura U-Net 3D residual de EN-1. Usa PyTorch, pero no al importar el modulo.

Migrada sin cambios de logica desde models/en1_inferencia_nuevo (1).py (research.md R14).
Tiene que ser identica a la del entrenamiento: load_state_dict(strict=True) compara
nombres y formas capa por capa, y cualquier diferencia hace fallar la carga.

Por eso los atributos que forman las claves del state_dict (e1, e2, e3, e4, cuello,
d4, d3, d2, d1, salida y reducir) conservan su nombre original en espanol: son parte
del formato del archivo de pesos, igual que sus claves, y renombrarlos rompe la carga.

torch se importa recien cuando se pide la red. La clase se define dentro de
_network_classes() (una sola vez) y se entrega con el __getattr__ del modulo (PEP 562):
`from en1_network import ResidualUnet3d` funciona igual, pero importar el modulo sin
pedir la clase no necesita torch. Asi la coleccion de pytest no falla donde torch no
esta instalado, como en el CI.
"""

from functools import cache
from typing import Any


def conv_block(in_channels, out_channels, groups=8):
    """Dos convoluciones 3D con GroupNorm y SiLU."""
    import torch.nn as nn

    g = min(groups, out_channels)
    while out_channels % g:
        g -= 1
    return nn.Sequential(
        nn.Conv3d(in_channels, out_channels, 3, padding=1, bias=False),
        nn.GroupNorm(g, out_channels),
        nn.SiLU(inplace=True),
        nn.Conv3d(out_channels, out_channels, 3, padding=1, bias=False),
        nn.GroupNorm(g, out_channels),
        nn.SiLU(inplace=True),
    )


@cache
def _network_classes() -> dict[str, type]:
    """Define las clases que heredan de torch. Se llama una sola vez, al pedirlas."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F  # noqa: N812 - alias habitual de PyTorch, igual que el original

    class ResidualUnet3d(nn.Module):
        """U-Net 3D de cuatro reducciones. La salida es canal_0 + red(entrada)."""

        def __init__(self, in_channels=2, base=16):
            super().__init__()
            c1, c2, c3, c4, c5 = base, base * 2, base * 4, base * 8, base * 16
            self.e1 = conv_block(in_channels, c1)
            self.e2 = conv_block(c1, c2)
            self.e3 = conv_block(c2, c3)
            self.e4 = conv_block(c3, c4)
            self.cuello = conv_block(c4, c5)
            self.d4 = conv_block(c5 + c4, c4)
            self.d3 = conv_block(c4 + c3, c3)
            self.d2 = conv_block(c3 + c2, c2)
            self.d1 = conv_block(c2 + c1, c1)
            self.salida = nn.Conv3d(c1, 1, 1)
            self.reducir = nn.MaxPool3d(2)
            nn.init.zeros_(self.salida.weight)
            nn.init.zeros_(self.salida.bias)

        @staticmethod
        def _upsample(x, target):
            return F.interpolate(
                x, size=target.shape[2:], mode="trilinear", align_corners=False
            )

        def forward(self, x):
            s1 = self.e1(x)
            s2 = self.e2(self.reducir(s1))
            s3 = self.e3(self.reducir(s2))
            s4 = self.e4(self.reducir(s3))
            y = self.cuello(self.reducir(s4))
            y = self.d4(torch.cat([self._upsample(y, s4), s4], 1))
            y = self.d3(torch.cat([self._upsample(y, s3), s3], 1))
            y = self.d2(torch.cat([self._upsample(y, s2), s2], 1))
            y = self.d1(torch.cat([self._upsample(y, s1), s1], 1))
            return x[:, :1] + self.salida(y)

    return {"ResidualUnet3d": ResidualUnet3d}


def __getattr__(name: str) -> Any:
    """Entrega ResidualUnet3d importando torch recien ahora (PEP 562)."""
    if name == "ResidualUnet3d":
        return _network_classes()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
