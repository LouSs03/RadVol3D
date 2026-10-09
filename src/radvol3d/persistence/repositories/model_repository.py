"""Acceso a la tabla model.

Catalogo de modelos: una fila por version, identificada por el par (model_name,
version). Muchos estudios y etapas apuntan a la misma fila. Los pesos no se guardan
aqui: viven en Supabase Storage.

La fecha de entrenamiento y la descripcion se guardan solo cuando llegan. Nunca se
completan con un valor estimado.
"""

from datetime import date
from typing import Any

from radvol3d.domain.entities import Model
from radvol3d.domain.exceptions import PersistenceError
from radvol3d.persistence.database_errors import execute_translated
from radvol3d.persistence.repositories.row_mapping import model_from_row

_MODEL_COLUMNS = "model_name, version, trained_on, description"


class ModelRepository:
    """Registra y consulta modelos dentro de la unidad de trabajo recibida."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def get_or_create(
        self,
        model_name: str,
        version: str,
        trained_on: date | None = None,
        description: str | None = None,
    ) -> Model:
        """Registra el modelo; si el par (nombre, version) ya existe, devuelve el existente.

        Al existir, la fila no se modifica: los datos opcionales que lleguen despues
        no sobrescriben los originales.
        """
        row = execute_translated(
            self._connection,
            "insert into model (model_name, version, trained_on, description) "
            "values (%s, %s, %s, %s) "
            "on conflict (model_name, version) do nothing "
            f"returning {_MODEL_COLUMNS}",
            (model_name, version, trained_on, description),
        ).fetchone()
        if row is not None:
            return model_from_row(row)

        # El par ya estaba registrado: se lee la fila que existe.
        existing = self.get(model_name, version)
        if existing is None:
            raise PersistenceError("No se pudo registrar el modelo en el catalogo.")
        return existing

    def get(self, model_name: str, version: str) -> Model | None:
        """Devuelve el modelo con ese nombre y version, o None si no existe."""
        row = execute_translated(
            self._connection,
            f"select {_MODEL_COLUMNS} from model where model_name = %s and version = %s",
            (model_name, version),
        ).fetchone()
        return model_from_row(row) if row is not None else None
