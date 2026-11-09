"""Inference-only architecture for the LUNA16 v3 training checkpoint."""

import math
from pathlib import Path

import torch
import torch.nn.functional as functional
from torch import Tensor, nn

from radvol3d import config


def ramp_filter(views: Tensor) -> Tensor:
    width = views.shape[-1]
    size = 1 << (4 * width - 1).bit_length()
    padded = functional.pad(views, (0, size - width, 0, 0), mode="replicate")
    frequencies = torch.fft.rfftfreq(size, device=views.device, dtype=torch.float32)
    hann = 0.5 + 0.5 * torch.cos(math.pi * frequencies / (frequencies[-1] + 1e-8))
    weights = (2.0 * frequencies) ** 0.5 * hann
    weights[0] = weights[1]
    spectrum = torch.fft.rfft(padded, n=size, dim=-1)
    return torch.fft.irfft(spectrum * weights, n=size, dim=-1)[..., :width]


class ProjectionGeometry(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fbp_scale = nn.Parameter(torch.tensor(2.2, dtype=torch.float32))
        self.fbp_bias = nn.Parameter(torch.tensor(0.0, dtype=torch.float32))
        self.bp_scale = nn.Parameter(torch.tensor(1.2, dtype=torch.float32))
        self.bp_bias = nn.Parameter(torch.tensor(0.0, dtype=torch.float32))

    @staticmethod
    def back_project(views: Tensor) -> Tensor:
        batch, _, depth, width = views.shape
        volumes = []
        for index, angle in enumerate(config.PROJECTION_ANGLES):
            slab = views[:, index:index + 1, :, :].unsqueeze(3)
            slab = slab.expand(batch, 1, depth, config.GRID_SIZE, width).contiguous()
            if angle == 90:
                slab = torch.rot90(slab, k=-1, dims=(3, 4))
            elif angle != 0:
                radians = -angle * math.pi / 180.0
                cosine, sine = math.cos(radians), math.sin(radians)
                transform = slab.new_zeros((batch, 3, 4))
                transform[:, 0, 0] = transform[:, 1, 1] = cosine
                transform[:, 0, 1] = -sine
                transform[:, 1, 0] = sine
                transform[:, 2, 2] = 1.0
                grid = functional.affine_grid(transform, slab.size(), align_corners=False)
                slab = functional.grid_sample(
                    slab, grid, mode="bilinear", padding_mode="border", align_corners=False
                )
            volumes.append(slab)
        return torch.cat(volumes, dim=1)

    def forward(self, views: Tensor) -> tuple[Tensor, Tensor]:
        plain = self.back_project(views.float())
        filtered = self.back_project(ramp_filter(views.float()))
        bp = (plain.mean(dim=1, keepdim=True) * self.bp_scale + self.bp_bias).clamp(0, 1)
        fbp = (filtered.mean(dim=1, keepdim=True) * self.fbp_scale + self.fbp_bias).clamp(0, 1)
        return torch.cat((fbp, bp, filtered), dim=1).to(views.dtype), fbp.to(views.dtype)


class ChannelSpatialAttention(nn.Module):
    def __init__(self, channels: int) -> None:
        super().__init__()
        reduced = max(4, channels // 4)
        self.ca = nn.Sequential(
            nn.AdaptiveAvgPool3d(1), nn.Conv3d(channels, reduced, 1), nn.SiLU(inplace=True),
            nn.Conv3d(reduced, channels, 1), nn.Sigmoid(),
        )
        self.sa = nn.Sequential(nn.Conv3d(2, 1, 3, padding=1, bias=False), nn.Sigmoid())

    def forward(self, tensor: Tensor) -> Tensor:
        tensor = tensor * self.ca(tensor)
        mean = tensor.mean(dim=1, keepdim=True)
        maximum = tensor.max(dim=1, keepdim=True).values
        return tensor * self.sa(torch.cat((mean, maximum), dim=1))


class ResidualBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, attention: bool = False) -> None:
        super().__init__()
        groups = math.gcd(8, out_channels)
        self.conv = nn.Sequential(
            nn.Conv3d(in_channels, out_channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, out_channels), nn.SiLU(inplace=True),
            nn.Conv3d(out_channels, out_channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, out_channels), nn.SiLU(inplace=True),
        )
        self.shortcut = (
            nn.Conv3d(in_channels, out_channels, 1, bias=False)
            if in_channels != out_channels else nn.Identity()
        )
        self.attention = ChannelSpatialAttention(out_channels) if attention else nn.Identity()

    def forward(self, tensor: Tensor) -> Tensor:
        return self.attention(self.conv(tensor) + self.shortcut(tensor))


class Luna16Reconstructor(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.geometry = ProjectionGeometry()
        c1, c2, c3, c4, c5 = 24, 48, 96, 192, 288
        self.e1 = ResidualBlock(2 + len(config.PROJECTION_ANGLES), c1)
        self.e2 = ResidualBlock(c1, c2)
        self.e3 = ResidualBlock(c2, c3, attention=True)
        self.e4 = ResidualBlock(c3, c4, attention=True)
        self.bottleneck = ResidualBlock(c4, c5, attention=True)
        self.d4 = ResidualBlock(c5 + c4, c4, attention=True)
        self.d3 = ResidualBlock(c4 + c3, c3, attention=True)
        self.d2 = ResidualBlock(c3 + c2, c2)
        self.d1 = ResidualBlock(c2 + c1, c1)
        self.pool = nn.MaxPool3d(2)
        self.output = nn.Conv3d(c1, 1, kernel_size=1)

    @staticmethod
    def join(tensor: Tensor, skip: Tensor) -> Tensor:
        expanded = functional.interpolate(
            tensor, size=skip.shape[2:], mode="trilinear", align_corners=False
        )
        return torch.cat((expanded, skip), dim=1)

    def forward(self, views: Tensor) -> Tensor:
        features, baseline = self.geometry(views)
        s1 = self.e1(features)
        s2 = self.e2(self.pool(s1))
        s3 = self.e3(self.pool(s2))
        s4 = self.e4(self.pool(s3))
        tensor = self.bottleneck(self.pool(s4))
        tensor = self.d4(self.join(tensor, s4))
        tensor = self.d3(self.join(tensor, s3))
        tensor = self.d2(self.join(tensor, s2))
        tensor = self.d1(self.join(tensor, s1))
        return (baseline + self.output(tensor)).clamp(0, 1)

    @classmethod
    def from_weights(cls, path: str | Path) -> "Luna16Reconstructor":
        state = torch.load(path, map_location="cpu", weights_only=True)
        if isinstance(state, dict) and "model_state_dict" in state:
            state = state["model_state_dict"]
        if not isinstance(state, dict) or not state:
            raise ValueError("Expected a non-empty LUNA16 state dictionary.")
        # Map the training checkpoint vocabulary, then require an exact match.
        names = {
            "geom": "geometry", "escala_fbp": "fbp_scale", "sesgo_fbp": "fbp_bias",
            "escala_bp": "bp_scale", "sesgo_bp": "bp_bias", "atajo": "shortcut",
            "atencion": "attention", "cuello": "bottleneck", "salida": "output",
        }
        translated = {
            ".".join(names.get(part, part) for part in key.split(".")): value
            for key, value in state.items()
        }
        if len(translated) != len(state):
            raise ValueError("Duplicate parameter keys in the LUNA16 checkpoint.")
        model = cls()
        model.load_state_dict(translated, strict=True)
        return model.eval().requires_grad_(False)
