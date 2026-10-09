"""Paso de filas de la base a entidades del dominio.

Varios repositorios unen su tabla con patient o con model, asi que el mapeo de
esas dos entidades vive aqui y no se repite.
"""

from collections.abc import Mapping
from typing import Any

from radvol3d.domain.entities import Model, Patient


def patient_from_row(row: Mapping[str, Any]) -> Patient:
    """Construye un Patient con las columnas de la tabla patient."""
    return Patient(
        patient_code=row["patient_code"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        national_id=row["national_id"],
    )


def model_from_row(row: Mapping[str, Any]) -> Model | None:
    """Construye un Model con las columnas de la tabla model.

    Devuelve None cuando la union externa no encontro modelo (model_name nulo).
    """
    if row["model_name"] is None:
        return None
    return Model(
        model_name=row["model_name"],
        version=row["version"],
        trained_on=row["trained_on"],
        description=row["description"],
    )
