"""Lee el .env de la raiz y expone la configuracion de la capa 3.

Las credenciales se guardan como SecretStr: ni str() ni repr() muestran su valor.
La configuracion se carga la primera vez que se pide, no al importar el modulo,
para poder importarlo (y probarlo) aunque falte el .env.

Hay dos grupos de variables:

- Settings: la base y el bucket de datos. Son obligatorias; sin ellas no se arranca.
- ModelSettings: el bucket de modelos y los pesos. Son opcionales; si falta una, el
  modelo correspondiente queda no disponible y la aplicacion arranca igual.
"""

from functools import cache
from pathlib import Path

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from radvol3d.domain.exceptions import ConfigurationError

# src/radvol3d/persistence/settings.py -> la raiz del repositorio esta tres niveles arriba.
ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    """Variables de entorno de la capa de persistencia.

    El entorno tiene prioridad sobre el archivo .env. Las cuatro variables son
    obligatorias y una variable vacia cuenta como faltante.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: SecretStr = Field(min_length=1)
    supabase_url: str = Field(min_length=1)
    supabase_service_key: SecretStr = Field(min_length=1)
    storage_bucket: str = Field(min_length=1)


@cache
def get_settings() -> Settings:
    """Carga la configuracion la primera vez y devuelve siempre la misma.

    Si falta alguna variable (o esta vacia), lanza ConfigurationError y el arranque
    se detiene. Un arranque fallido no se guarda: una llamada posterior vuelve a leer.
    """
    try:
        return Settings()
    except ValidationError as error:
        raise ConfigurationError(_missing_variables_message(error)) from None


def _missing_variables_message(error: ValidationError) -> str:
    """Mensaje en espanol con los NOMBRES de las variables que fallaron.

    Se arma solo con los nombres de los campos, nunca con el texto de pydantic: ese
    texto incluye el valor recibido (input_value) y podria mostrar una clave.
    """
    failed = {str(detail["loc"][0]) for detail in error.errors() if detail["loc"]}
    names = [field.upper() for field in Settings.model_fields if field in failed]
    if not names:
        return "La configuracion no es valida. Revisa el archivo .env."
    if len(names) == 1:
        return f"Falta la variable {names[0]} en .env"
    return f"Faltan las variables {', '.join(names)} en .env"


class ModelSettings(BaseSettings):
    """Variables de los modelos (data-model.md §6 de la funcionalidad 002).

    Todas son opcionales. Una variable presente pero vacia (como las deja
    .env.example) cuenta como no definida y toma su valor por omision: por eso
    env_ignore_empty. Las credenciales de Supabase son las mismas de Settings.
    """

    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    model_bucket: str | None = None
    en1_weights_object: str | None = None
    en2_weights_object: str | None = None
    model_cache_dir: Path = Path(".cache/models")
    reconstruction_strategy: str = "en1"


@cache
def get_model_settings() -> ModelSettings:
    """Carga la configuracion de los modelos la primera vez. Nunca falla por una variable."""
    return ModelSettings()
