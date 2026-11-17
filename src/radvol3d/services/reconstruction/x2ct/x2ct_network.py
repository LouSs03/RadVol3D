"""Arquitecturas PyTorch para X2CT-GAN (1 vista) sin importar torch al cargar el modulo.

Sigue el patron de `en1_network.py`: las clases basadas en `torch.nn.Module` se
definen de forma perezosa mediante `__getattr__` (PEP 562) para que la coleccion
de pruebas y el chequeo de capas funcionen sin PyTorch en el arranque.

Los nombres de los submodulos internos (`encoder_layer`, `linker_layer*`,
`base_link`, `decoder_layer*`, `conv_block`, `block`, `compress_block`, `model`)
conservan exactamente el esquema de claves de `30_net_G.pth` y `30_net_D.pth`
para permitir `load_state_dict(..., strict=True)`.
"""

import functools
import math
from functools import cache
from typing import Any


@cache
def _network_classes() -> dict[str, Any]:
    """Define generador y discriminador 3D de X2CT-GAN una sola vez."""
    import torch
    import torch.nn as nn

    class DenseLayer2d(nn.Sequential):
        def __init__(
            self,
            num_input_features: int,
            growth_rate: int,
            bn_size: int,
            norm_layer: Any,
            activation: Any,
            use_bias: bool,
        ) -> None:
            super().__init__()
            self.add_module("norm1", norm_layer(num_input_features))
            self.add_module("relu1", activation)
            self.add_module(
                "conv1",
                nn.Conv2d(
                    num_input_features,
                    bn_size * growth_rate,
                    kernel_size=1,
                    stride=1,
                    bias=use_bias,
                ),
            )
            self.add_module("norm2", norm_layer(bn_size * growth_rate))
            self.add_module("relu2", activation)
            self.add_module(
                "conv2",
                nn.Conv2d(
                    bn_size * growth_rate,
                    growth_rate,
                    kernel_size=3,
                    stride=1,
                    padding=1,
                    bias=use_bias,
                ),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            new_features = super().forward(x)
            return torch.cat([x, new_features], 1)

    class DenseBlock2d(nn.Module):
        def __init__(
            self,
            num_layers: int,
            num_input_features: int,
            bn_size: int,
            growth_rate: int,
            norm_layer: Any,
            activation: Any,
            use_bias: bool,
        ) -> None:
            super().__init__()
            layers = [
                DenseLayer2d(
                    num_input_features + i * growth_rate,
                    growth_rate,
                    bn_size,
                    norm_layer,
                    activation,
                    use_bias,
                )
                for i in range(num_layers)
            ]
            self.conv_block = nn.Sequential(*layers)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.conv_block(x)

    class UpsampleTransposedConvBlock(nn.Module):
        def __init__(
            self,
            kernel_size: int,
            input_channel: int,
            output_channel: int,
            norm_layer: Any,
            scale_factor: int = 2,
            activation: Any = None,
            use_bias: bool = True,
        ) -> None:
            super().__init__()
            pad = int(kernel_size // 2)
            act = activation if activation is not None else nn.ReLU(True)
            self.block = nn.Sequential(
                nn.ConvTranspose3d(
                    input_channel,
                    output_channel,
                    kernel_size=kernel_size,
                    stride=scale_factor,
                    padding=pad,
                    output_padding=pad,
                    bias=use_bias,
                ),
                norm_layer(output_channel),
                act,
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.block(x)

    class Upsample3dBlock(nn.Module):
        def __init__(
            self,
            kernel_size: int,
            input_channel: int,
            output_channel: int,
            norm_layer: Any,
            scale_factor: int = 2,
            upsample_mode: str = "nearest",
            activation: Any = None,
            use_bias: bool = True,
        ) -> None:
            super().__init__()
            act = activation if activation is not None else nn.ReLU(True)
            self.block = nn.Sequential(
                nn.Upsample(scale_factor=scale_factor, mode=upsample_mode),
                nn.Conv3d(
                    input_channel,
                    output_channel,
                    kernel_size=kernel_size,
                    padding=int(kernel_size // 2),
                    bias=use_bias,
                ),
                norm_layer(output_channel),
                act,
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.block(x)

    class Upsample3dUnit(nn.Module):
        def __init__(
            self,
            kernel_size: int,
            input_channel: int,
            output_channel: int,
            norm_layer: Any,
            scale_factor: int = 2,
            upsample_mode: str = "transposed",
            activation: Any = None,
            use_bias: bool = True,
        ) -> None:
            super().__init__()
            if upsample_mode in ("trilinear", "nearest"):
                self.block: nn.Module = Upsample3dBlock(
                    kernel_size,
                    input_channel,
                    output_channel,
                    norm_layer,
                    scale_factor,
                    upsample_mode,
                    activation,
                    use_bias,
                )
            elif upsample_mode == "transposed":
                self.block = UpsampleTransposedConvBlock(
                    kernel_size,
                    input_channel,
                    output_channel,
                    norm_layer,
                    scale_factor,
                    activation,
                    use_bias,
                )
            else:
                raise ValueError(f"Unsupported upsample_mode: {upsample_mode}")

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.block(x)

    class DimensionUpsampleCutBlock(nn.Module):
        def __init__(
            self,
            input_channel: int,
            output_channel: int,
            norm_layer2d: Any,
            norm_layer3d: Any,
            activation: Any,
            use_bias: bool = True,
        ) -> None:
            super().__init__()
            self.output_channel = output_channel
            self.compress_block = nn.Sequential(
                nn.Conv2d(input_channel, output_channel, kernel_size=1, padding=0, bias=use_bias),
                norm_layer2d(output_channel),
                activation,
            )
            self.conv_block = nn.Sequential(
                nn.Conv3d(
                    output_channel,
                    output_channel,
                    kernel_size=(3, 3, 3),
                    padding=(1, 1, 1),
                    bias=use_bias,
                ),
                norm_layer3d(output_channel),
                activation,
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            batch, _, height, width = x.size()
            projected = self.compress_block(x).unsqueeze(2).expand(
                batch, self.output_channel, height, height, width
            )
            return self.conv_block(projected)

    class UnetLikeDenseDimensionNet(nn.Module):
        """Generador 2D->3D de X2CT-GAN (`UNetLike_DownStep5`)."""

        def __init__(
            self,
            encoder_input_channels: int = 1,
            decoder_output_channels: int = 1,
            decoder_begin_size: int = 4,
            encoder_block_list: tuple[int, ...] = (6, 12, 24, 16, 6),
            decoder_block_list: tuple[int, ...] = (1, 2, 2, 2, 2, 0),
            growth_rate: int = 32,
            upsample_mode: str = "transposed",
            decoder_feature_out: bool = False,
        ) -> None:
            super().__init__()
            encoder_channel_list = [64]
            decoder_channel_list = [16, 16, 32, 64, 128, 256]
            self.decoder_channel_list = decoder_channel_list
            self.decoder_block_list = decoder_block_list
            self.n_downsampling = len(encoder_block_list)
            self.decoder_begin_size = decoder_begin_size
            self.decoder_feature_out = decoder_feature_out
            activation = nn.ReLU(True)
            bn_size = 4

            enc_norm = functools.partial(
                nn.InstanceNorm2d, affine=False, track_running_stats=True
            )
            dec_norm = functools.partial(
                nn.InstanceNorm3d, affine=False, track_running_stats=True
            )

            self.encoder_layer = nn.Sequential(
                nn.ReflectionPad2d(3),
                nn.Conv2d(encoder_input_channels, encoder_channel_list[0], kernel_size=7, bias=True),
                enc_norm(encoder_channel_list[0]),
                activation,
            )

            num_input_channels = encoder_channel_list[0]
            for index, num_layers in enumerate(encoder_block_list):
                down_layers: list[nn.Module] = [
                    enc_norm(num_input_channels),
                    activation,
                    nn.Conv2d(
                        num_input_channels,
                        num_input_channels,
                        kernel_size=3,
                        stride=2,
                        padding=1,
                        bias=True,
                    ),
                    DenseBlock2d(
                        num_layers,
                        num_input_channels,
                        bn_size,
                        growth_rate,
                        enc_norm,
                        activation,
                        use_bias=True,
                    ),
                ]
                num_input_channels += num_layers * growth_rate
                if index == self.n_downsampling - 1:
                    down_layers.append(nn.AdaptiveAvgPool2d(1))
                else:
                    num_out = num_input_channels // 2
                    down_layers.extend(
                        [
                            enc_norm(num_input_channels),
                            activation,
                            nn.Conv2d(num_input_channels, num_out, kernel_size=1, bias=True),
                        ]
                    )
                    num_input_channels = num_out
                encoder_channel_list.append(num_input_channels)
                setattr(self, f"encoder_layer{index}", nn.Sequential(*down_layers))

            self.base_link = nn.Sequential(
                nn.Linear(encoder_channel_list[-1], (decoder_begin_size**3) * decoder_channel_list[-1]),
                nn.Dropout(0.5),
                activation,
            )

            for index, in_ch in enumerate(encoder_channel_list[:-1]):
                link_block = DimensionUpsampleCutBlock(
                    in_ch, decoder_channel_list[index], enc_norm, dec_norm, activation, use_bias=True
                )
                setattr(self, f"linker_layer{index}", nn.Sequential(link_block))

            for index, out_ch in enumerate(decoder_channel_list[:-1]):
                in_ch = decoder_channel_list[index + 1]
                compress_layers: list[nn.Module] = []
                layers: list[nn.Module] = []
                if index != len(decoder_channel_list) - 2:
                    compress_layers.extend(
                        [
                            nn.Conv3d(in_ch * 2, in_ch, kernel_size=3, padding=1, bias=True),
                            dec_norm(in_ch),
                            activation,
                        ]
                    )
                    for _ in range(decoder_block_list[index + 1]):
                        layers.extend(
                            [
                                nn.Conv3d(in_ch, in_ch, kernel_size=3, padding=1, bias=True),
                                dec_norm(in_ch),
                                activation,
                            ]
                        )
                layers.append(
                    Upsample3dUnit(
                        3,
                        in_ch,
                        out_ch,
                        dec_norm,
                        scale_factor=2,
                        upsample_mode=upsample_mode,
                        activation=activation,
                        use_bias=True,
                    )
                )
                if decoder_feature_out:
                    setattr(self, f"decoder_compress_layer{index}", nn.Sequential(*compress_layers))
                    setattr(self, f"decoder_layer{index}", nn.Sequential(*layers))
                else:
                    setattr(self, f"decoder_layer{index}", nn.Sequential(*(compress_layers + layers)))

            last_ch = decoder_channel_list[0]
            last_compress: list[nn.Module] = [
                nn.Conv3d(last_ch * 2, last_ch, kernel_size=3, padding=1, bias=True),
                dec_norm(last_ch),
                activation,
            ]
            last_layers: list[nn.Module] = []
            for _ in range(decoder_block_list[0]):
                last_layers.extend(
                    [
                        nn.Conv3d(last_ch, last_ch, kernel_size=3, padding=1, bias=True),
                        dec_norm(last_ch),
                        activation,
                    ]
                )
            if decoder_feature_out:
                setattr(self, "decoder_compress_layer-1", nn.Sequential(*last_compress))
                setattr(self, "decoder_layer-1", nn.Sequential(*last_layers))
            else:
                setattr(self, "decoder_layer-1", nn.Sequential(*(last_compress + last_layers)))
            self.decoder_layer = nn.Sequential(
                nn.Conv3d(last_ch, decoder_output_channels, kernel_size=7, padding=3, bias=True),
                nn.ReLU(),
            )

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            skips: list[torch.Tensor] = []
            current = self.encoder_layer(x)
            for i in range(self.n_downsampling):
                skips.append(getattr(self, f"linker_layer{i}")(current))
                current = getattr(self, f"encoder_layer{i}")(current)

            current = self.base_link(current.view(current.size(0), -1))
            current = current.view(
                current.size(0),
                self.decoder_channel_list[-1],
                self.decoder_begin_size,
                self.decoder_begin_size,
                self.decoder_begin_size,
            )

            for i in range(self.n_downsampling - 1, -2, -1):
                if i == self.n_downsampling - 1:
                    if self.decoder_feature_out:
                        current = getattr(self, f"decoder_compress_layer{i}")(current)
                    current = getattr(self, f"decoder_layer{i}")(current)
                else:
                    merged = torch.cat((current, skips[i + 1]), dim=1)
                    if self.decoder_feature_out:
                        merged = getattr(self, f"decoder_compress_layer{i}")(merged)
                    current = getattr(self, f"decoder_layer{i}")(merged)
            return self.decoder_layer(current)

    class TransposedAndAdd(nn.Module):
        """Alinea y suma representaciones 3D de PA y Lateral en espacio canonico."""

        def __init__(self, view1_order: tuple[int, ...], view2_order: tuple[int, ...]) -> None:
            super().__init__()
            import numpy as np

            self.permute_view1 = tuple(int(i) for i in np.argsort(view1_order))
            self.permute_view2 = tuple(int(i) for i in np.argsort(view2_order))

        def forward(self, first: torch.Tensor, second: torch.Tensor) -> torch.Tensor:
            return first.permute(*self.permute_view1) + second.permute(*self.permute_view2)

    class MultiViewUnetLikeDenseDimensionNet(nn.Module):
        """Generador biplanar 2D->3D de X2CT-GAN (`90_net_G.pth`)."""

        def __init__(
            self,
            view1_model: UnetLikeDenseDimensionNet,
            view2_model: UnetLikeDenseDimensionNet,
            view1_order: tuple[int, ...] = (0, 1, 3, 2, 4),
            view2_order: tuple[int, ...] = (0, 1, 4, 2, 3),
            decoder_output_channels: int = 1,
            decoder_block_list: tuple[int, ...] = (1, 1, 1, 1, 1, 0),
            upsample_mode: str = "transposed",
        ) -> None:
            super().__init__()
            self.view1Model = view1_model
            self.view2Model = view2_model
            self.view1Order = tuple(view1_order)
            self.view2Order = tuple(view2_order)
            self.n_downsampling = view2_model.n_downsampling
            self.decoder_channel_list = view2_model.decoder_channel_list
            self.decoder_block_list = tuple(decoder_block_list)
            activation = nn.ReLU(True)
            dec_norm = functools.partial(
                nn.InstanceNorm3d, affine=False, track_running_stats=True
            )

            for index, out_ch in enumerate(self.decoder_channel_list[:-1]):
                in_ch = self.decoder_channel_list[index + 1]
                layers: list[nn.Module] = []
                if index != len(self.decoder_channel_list) - 2:
                    layers.extend(
                        [
                            nn.Conv3d(in_ch * 2, in_ch, kernel_size=3, padding=1, bias=True),
                            dec_norm(in_ch),
                            activation,
                        ]
                    )
                    for _ in range(self.decoder_block_list[index + 1]):
                        layers.extend(
                            [
                                nn.Conv3d(in_ch, in_ch, kernel_size=3, padding=1, bias=True),
                                dec_norm(in_ch),
                                activation,
                            ]
                        )
                layers.append(
                    Upsample3dUnit(
                        3,
                        in_ch,
                        out_ch,
                        dec_norm,
                        scale_factor=2,
                        upsample_mode=upsample_mode,
                        activation=activation,
                        use_bias=True,
                    )
                )
                setattr(self, f"decoder_layer{index}", nn.Sequential(*layers))

            last_ch = self.decoder_channel_list[0]
            last_layers: list[nn.Module] = [
                nn.Conv3d(last_ch * 2, last_ch, kernel_size=3, padding=1, bias=True),
                dec_norm(last_ch),
                activation,
            ]
            for _ in range(self.decoder_block_list[0]):
                last_layers.extend(
                    [
                        nn.Conv3d(last_ch, last_ch, kernel_size=3, padding=1, bias=True),
                        dec_norm(last_ch),
                        activation,
                    ]
                )
            setattr(self, "decoder_layer-1", nn.Sequential(*last_layers))
            self.decoder_layer = nn.Sequential(
                nn.Conv3d(last_ch, decoder_output_channels, kernel_size=7, padding=3, bias=True),
                nn.ReLU(),
            )
            self.transposed_layer = TransposedAndAdd(self.view1Order, self.view2Order)

        @staticmethod
        def _encode_view(model: UnetLikeDenseDimensionNet, image: torch.Tensor) -> tuple[torch.Tensor, list[torch.Tensor]]:
            skips: list[torch.Tensor] = []
            current = model.encoder_layer(image)
            for i in range(model.n_downsampling):
                skips.append(getattr(model, f"linker_layer{i}")(current))
                current = getattr(model, f"encoder_layer{i}")(current)
            current = model.base_link(current.view(current.size(0), -1))
            current = current.view(
                current.size(0),
                model.decoder_channel_list[-1],
                model.decoder_begin_size,
                model.decoder_begin_size,
                model.decoder_begin_size,
            )
            return current, skips

        def forward(
            self, inputs: list[torch.Tensor] | tuple[torch.Tensor, torch.Tensor]
        ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
            if len(inputs) != 2:
                raise ValueError("MultiView X2CT requiere exactamente 2 vistas (PA, Lateral).")
            v1, skips1 = self._encode_view(self.view1Model, inputs[0])
            v2, skips2 = self._encode_view(self.view2Model, inputs[1])
            fused: torch.Tensor | None = None

            for i in range(self.n_downsampling - 1, -2, -1):
                if i == self.n_downsampling - 1:
                    v1 = getattr(self.view1Model, f"decoder_compress_layer{i}")(v1)
                    v2 = getattr(self.view2Model, f"decoder_compress_layer{i}")(v2)
                    view_avg = self.transposed_layer(v1, v2) / 2.0
                    v1 = view_avg.permute(*self.view1Order)
                    v2 = view_avg.permute(*self.view2Order)
                    fused = getattr(self, f"decoder_layer{i}")(view_avg)
                else:
                    v1 = getattr(self.view1Model, f"decoder_compress_layer{i}")(
                        torch.cat((v1, skips1[i + 1]), dim=1)
                    )
                    v2 = getattr(self.view2Model, f"decoder_compress_layer{i}")(
                        torch.cat((v2, skips2[i + 1]), dim=1)
                    )
                    view_avg = self.transposed_layer(v1, v2) / 2.0
                    v1 = view_avg.permute(*self.view1Order)
                    v2 = view_avg.permute(*self.view2Order)
                    fused = getattr(self, f"decoder_layer{i}")(torch.cat((view_avg, fused), dim=1))
                v1 = getattr(self.view1Model, f"decoder_layer{i}")(v1)
                v2 = getattr(self.view2Model, f"decoder_layer{i}")(v2)

            return (
                self.view1Model.decoder_layer(v1),
                self.view2Model.decoder_layer(v2),
                self.decoder_layer(fused),
            )

    class NLayer3dDiscriminator(nn.Module):
        """Discriminador PatchGAN 3D condicional (`30_net_D.pth`)."""

        def __init__(
            self,
            input_nc: int = 2,
            ndf: int = 64,
            n_layers: int = 3,
            n_out_channels: int = 1,
        ) -> None:
            super().__init__()
            dec_norm = functools.partial(
                nn.InstanceNorm3d, affine=False, track_running_stats=True
            )
            kw = 4
            padw = int(math.ceil((kw - 1.0) / 2.0))
            # En el entrenamiento original de X2CT, `use_bias` evaluaba False con InstanceNorm3d.
            use_bias = False
            layers: list[nn.Module] = [
                nn.Conv3d(input_nc, ndf, kernel_size=kw, stride=2, padding=padw),
                nn.LeakyReLU(0.2, True),
            ]
            nf_mult = 1
            for n in range(1, n_layers):
                nf_mult_prev = nf_mult
                nf_mult = min(2**n, 8)
                layers.extend(
                    [
                        nn.Conv3d(
                            ndf * nf_mult_prev,
                            ndf * nf_mult,
                            kernel_size=kw,
                            stride=2,
                            padding=padw,
                            bias=use_bias,
                        ),
                        dec_norm(ndf * nf_mult),
                        nn.LeakyReLU(0.2, True),
                    ]
                )
            nf_mult_prev = nf_mult
            nf_mult = min(2**n_layers, 8)
            layers.extend(
                [
                    nn.Conv3d(
                        ndf * nf_mult_prev,
                        ndf * nf_mult,
                        kernel_size=kw,
                        stride=1,
                        padding=padw,
                        bias=use_bias,
                    ),
                    dec_norm(ndf * nf_mult),
                    nn.LeakyReLU(0.2, True),
                    nn.Conv3d(ndf * nf_mult, n_out_channels, kernel_size=kw, stride=1, padding=padw),
                ]
            )
            self.model = nn.Sequential(*layers)

        def forward(self, x: torch.Tensor) -> list[torch.Tensor]:
            return [self.model(x)]

    def build_x2ct_generator(
        input_shape: int = 128, *, decoder_feature_out: bool = False
    ) -> UnetLikeDenseDimensionNet:
        return UnetLikeDenseDimensionNet(
            encoder_input_channels=1,
            decoder_output_channels=1,
            decoder_begin_size=input_shape // 32,
            decoder_feature_out=decoder_feature_out,
        )

    def build_x2ct_2view_generator(input_shape: int = 128) -> MultiViewUnetLikeDenseDimensionNet:
        return MultiViewUnetLikeDenseDimensionNet(
            view1_model=build_x2ct_generator(input_shape, decoder_feature_out=True),
            view2_model=build_x2ct_generator(input_shape, decoder_feature_out=True),
        )

    def build_x2ct_discriminator() -> NLayer3dDiscriminator:
        return NLayer3dDiscriminator(input_nc=2, ndf=64, n_layers=3, n_out_channels=1)

    return {
        "UnetLikeDenseDimensionNet": UnetLikeDenseDimensionNet,
        "MultiViewUnetLikeDenseDimensionNet": MultiViewUnetLikeDenseDimensionNet,
        "TransposedAndAdd": TransposedAndAdd,
        "NLayer3dDiscriminator": NLayer3dDiscriminator,
        "build_x2ct_generator": build_x2ct_generator,
        "build_x2ct_2view_generator": build_x2ct_2view_generator,
        "build_x2ct_discriminator": build_x2ct_discriminator,
    }


def __getattr__(name: str) -> Any:
    """Entrega las arquitecturas importando torch recien al solicitarlas (PEP 562)."""
    classes = _network_classes()
    if name in classes:
        return classes[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
