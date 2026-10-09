"""U-Net 3D residual con supervision profunda para segmentar tumor (EN-2).

Usa PyTorch, pero no al importar el modulo.

Migrada sin cambios de logica desde models/en2_inferencia.py (research.md R14). Tiene
que ser identica a la del entrenamiento: load_state_dict(strict=True) compara nombres
y formas capa por capa.

Por eso los atributos que forman las claves del state_dict (entrada, bajadas, subidas,
fusiones y cabezas en la red; c1, n1, c2, n2, act y salto en cada bloque) conservan su
nombre original en espanol: son parte del formato del archivo de pesos, igual que sus
claves, y renombrarlos rompe la carga.

torch se importa recien cuando se pide una de las clases. Se definen dentro de
_network_classes() (una sola vez) y se entregan con el __getattr__ del modulo (PEP 562):
`from lung_unet_network import SegmentationUnet3d` funciona igual, pero importar el
modulo sin pedir las clases no necesita torch.
"""

from functools import cache
from typing import Any

_CLASS_NAMES = ("ResidualBlock", "SegmentationUnet3d")


def instance_norm(channels):
    # InstanceNorm: no depende del tamano del lote, necesario con lote de 2.
    import torch.nn as nn

    return nn.InstanceNorm3d(channels, affine=True)


@cache
def _network_classes() -> dict[str, type]:
    """Define las clases que heredan de torch. Se llama una sola vez, al pedirlas."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F  # noqa: N812 - alias habitual de PyTorch, igual que el original

    class ResidualBlock(nn.Module):
        """Dos convoluciones 3D con salto residual."""

        def __init__(self, in_channels, out_channels):
            super().__init__()
            self.c1 = nn.Conv3d(in_channels, out_channels, 3, padding=1, bias=False)
            self.n1 = instance_norm(out_channels)
            self.c2 = nn.Conv3d(out_channels, out_channels, 3, padding=1, bias=False)
            self.n2 = instance_norm(out_channels)
            self.act = nn.LeakyReLU(0.01, inplace=True)
            self.salto = (
                nn.Identity()
                if in_channels == out_channels
                else nn.Sequential(
                    nn.Conv3d(in_channels, out_channels, 1, bias=False),
                    instance_norm(out_channels),
                )
            )

        def forward(self, x):
            y = self.act(self.n1(self.c1(x)))
            y = self.n2(self.c2(y))
            return self.act(y + self.salto(x))

    class SegmentationUnet3d(nn.Module):
        """Entrada (N, 1, D, H, W) en [0, 1].

        Salida: lista de logits, el primero a resolucion plena.
        """

        def __init__(self, channels=(16, 32, 64, 128, 192), in_channels=1, supervision=3):
            super().__init__()
            self.channels = tuple(int(c) for c in channels)
            self.supervision = int(supervision)
            n = len(self.channels)

            self.entrada = ResidualBlock(in_channels, self.channels[0])
            self.bajadas = nn.ModuleList(
                [
                    nn.Sequential(
                        nn.Conv3d(
                            self.channels[i - 1],
                            self.channels[i],
                            3,
                            stride=2,
                            padding=1,
                            bias=False,
                        ),
                        instance_norm(self.channels[i]),
                        nn.LeakyReLU(0.01, inplace=True),
                        ResidualBlock(self.channels[i], self.channels[i]),
                    )
                    for i in range(1, n)
                ]
            )
            self.subidas = nn.ModuleList(
                [
                    nn.ConvTranspose3d(
                        self.channels[i], self.channels[i - 1], 2, stride=2, bias=False
                    )
                    for i in range(n - 1, 0, -1)
                ]
            )
            self.fusiones = nn.ModuleList(
                [
                    ResidualBlock(self.channels[i - 1] * 2, self.channels[i - 1])
                    for i in range(n - 1, 0, -1)
                ]
            )
            self.cabezas = nn.ModuleList(
                [nn.Conv3d(self.channels[i], 1, 1) for i in range(self.supervision)]
            )

        def features(self, x):
            """Devuelve (lista de mapas del decodificador, cuello). Se usa en Grad-CAM."""
            skips = [self.entrada(x)]
            for down in self.bajadas:
                skips.append(down(skips[-1]))
            bottleneck = skips[-1]
            y = bottleneck
            decoded = []
            for k, (up, fuse) in enumerate(zip(self.subidas, self.fusiones, strict=False)):
                y = up(y)
                s = skips[-2 - k]
                if y.shape[2:] != s.shape[2:]:
                    y = F.interpolate(y, size=s.shape[2:], mode="trilinear", align_corners=False)
                y = fuse(torch.cat([y, s], dim=1))
                decoded.append(y)
            return decoded, bottleneck

        def forward(self, x):
            decoded, _ = self.features(x)
            # decoded[-1] esta a resolucion plena, decoded[-2] a 1/2, decoded[-3] a 1/4
            return [self.cabezas[i](decoded[-1 - i]) for i in range(self.supervision)]

    return {"ResidualBlock": ResidualBlock, "SegmentationUnet3d": SegmentationUnet3d}


def __getattr__(name: str) -> Any:
    """Entrega las clases de la red importando torch recien ahora (PEP 562)."""
    if name in _CLASS_NAMES:
        return _network_classes()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
