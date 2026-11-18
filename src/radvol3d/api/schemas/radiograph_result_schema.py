"""Esquemas del resultado de un estudio de una radiografia (visor propio de ese modo)."""

from typing import Any

from pydantic import BaseModel, Field


class RadiographResultResponse(BaseModel):
    """Lo que necesita el visor del modo de una radiografia.

    No trae lesiones ni malla del tumor: este modo no tiene segmentacion.
    """

    study_code: str = Field(description="Codigo del estudio")
    model_name: str | None = Field(default=None, description="Modelo que reconstruyo")
    voxel_mm: list[float] = Field(
        description="Tamano del voxel en los ejes (R, A, S) del volumen, en mm "
        "(en unidades relativas si relative_measurements)"
    )
    relative_measurements: bool = Field(
        description="True si el DICOM no traia tamano de pixel: las medidas no son mm reales"
    )
    warnings: list[str] = Field(default_factory=list, description="Avisos de la reconstruccion")
    input_size_px: list[int] | None = Field(
        default=None, description="Filas y columnas de la placa original"
    )
    timings_s: dict[str, float] = Field(default_factory=dict, description="Tiempos de X2CT-GAN")
    volume_url: str = Field(description="Volumen reconstruido (.npy, convenio del sistema)")
    surface_url: str = Field(description="Superficie del aire pulmonar (.glb, en mm)")
    input_image_url: str | None = Field(default=None, description="Placa que vio el modelo")
    metadata_url: str | None = Field(default=None, description="metadatos.json de X2CT-GAN")
    nifti_url: str | None = Field(default=None, description="Volumen en HU (.nii.gz)")


class RadiographValidationResponse(BaseModel):
    """La validacion frontal: la placa frente a la radiografia simulada desde la TC.

    validation es el contenido de validacion.json (services/reconstruction/
    frontal_validation.py): NCC, escala y desplazamiento de ajuste, pulmones 2D y la nota.
    """

    study_code: str = Field(description="Codigo del estudio")
    validation: dict[str, Any] = Field(description="Valores de validacion.json")
    input_image_url: str = Field(description="Placa que vio el modelo (PNG)")
    simulated_url: str = Field(description="Radiografia simulada desde la reconstruccion (PNG)")
    overlay_url: str = Field(description="Placa con los contornos de los pulmones (PNG)")
    json_url: str = Field(description="validacion.json")
