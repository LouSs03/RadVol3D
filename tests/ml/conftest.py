"""Fixtures de las pruebas con los modelos reales (marcador "ml").

Necesitan PyTorch (el extra "ml") y los artefactos de contracts/model_artifacts.md: los
pesos y la referencia de regresion que genera scripts/generate_regression_reference.py.
Los buscan primero en la cache local (MODEL_CACHE_DIR de .env.test, o .cache/models) y,
si faltan, los bajan del bucket de modelos de .env.test. Cada objeto se verifica contra
el SHA-256 del manifiesto. Si falta torch, el manifiesto o un artefacto, las pruebas se
omiten con un mensaje que dice que falta. El CI no instala torch: alli siempre se omiten.

Las fixtures de la base y del bucket de prueba (y su limpieza) se reutilizan de
tests/integration/conftest.py, para el estudio de ejemplo.
"""

import hashlib
import json
from pathlib import Path

import pytest
from dotenv import dotenv_values

from radvol3d.domain.exceptions import StorageError
from radvol3d.persistence.model_weights_store import ModelWeightsStore
from radvol3d.persistence.object_storage import ObjectStorage
from tests.integration.conftest import (  # noqa: F401 - fixtures que pytest descubre aqui
    cleanup_after_test,
    created_patient_codes,
    database,
    make_study_code,
    object_storage,
    test_settings,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests" / "ml" / "reference" / "manifest.json"
ENV_TEST_FILE = ROOT / ".env.test"
EN1_WEIGHTS = "reconstruction_en1/1.0.0/weights.pth"
EN2_WEIGHTS = "segmentation_lung/1.0.0/weights.pth"


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Toda prueba de esta carpeta lleva el marcador ml, aunque se olvide en el modulo."""
    here = Path(__file__).parent
    for item in items:
        if here in Path(item.fspath).parents:
            item.add_marker(pytest.mark.ml)


@pytest.fixture(autouse=True, scope="session")
def requires_torch() -> None:
    pytest.importorskip("torch", reason="Las pruebas ml necesitan el extra 'ml' (PyTorch).")


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ModelArtifacts:
    """Ruta local y verificada de cada artefacto del manifiesto."""

    def __init__(self, manifest: dict, cache_dir: Path, request: pytest.FixtureRequest) -> None:
        self.manifest = manifest
        self.cache_dir = cache_dir
        self._request = request
        self._expected = {
            EN1_WEIGHTS: manifest["weights"]["en1"]["sha256"],
            EN2_WEIGHTS: manifest["weights"]["en2"]["sha256"],
        }
        for case in manifest["cases"]:
            for entry in [case["input"], *case["outputs"]]:
                if "object" in entry and "sha256" in entry:
                    self._expected[entry["object"]] = entry["sha256"]
        self._store: ModelWeightsStore | None = None

    def path(self, object_path: str) -> Path:
        local = self.cache_dir / object_path
        if not local.is_file():
            local = self._download(object_path)
        expected = self._expected.get(object_path)
        if expected is not None and sha256_of(local) != expected:
            pytest.fail(
                f"{object_path} no coincide con el SHA-256 del manifiesto: la referencia o "
                "los pesos cambiaron. Regenera la referencia con "
                "scripts/generate_regression_reference.py."
            )
        return local

    def _download(self, object_path: str) -> Path:
        if self._store is None:
            values = dotenv_values(ENV_TEST_FILE) if ENV_TEST_FILE.is_file() else {}
            bucket = values.get("MODEL_BUCKET")
            if not bucket:
                pytest.skip(
                    f"Falta {object_path} en {self.cache_dir} y .env.test no define "
                    "MODEL_BUCKET para bajarlo."
                )
            settings = self._request.getfixturevalue("test_settings")
            storage = ObjectStorage.from_settings(settings, bucket=bucket)
            self._store = ModelWeightsStore(storage, self.cache_dir)
        try:
            return self._store.fetch(object_path)
        except StorageError:
            pytest.skip(f"No se pudo obtener {object_path} del bucket de modelos.")

    def environment_note(self) -> str:
        """El entorno de la referencia frente al actual, para los mensajes de fallo."""
        import platform

        import numpy
        import scipy
        import torch

        current = {
            "torch": torch.__version__,
            "numpy": numpy.__version__,
            "scipy": scipy.__version__,
            "platform": platform.platform(),
        }
        reference = self.manifest.get("environment", {})
        differences = {
            key: (reference.get(key), value)
            for key, value in current.items()
            if reference.get(key) != value
        }
        return f"entorno distinto del de la referencia (referencia, actual): {differences}"


@pytest.fixture(scope="session")
def model_artifacts(request: pytest.FixtureRequest) -> ModelArtifacts:
    if not MANIFEST.is_file():
        pytest.skip(
            "Falta tests/ml/reference/manifest.json: corre "
            "scripts/generate_regression_reference.py en la maquina que tiene models/."
        )
    values = dotenv_values(ENV_TEST_FILE) if ENV_TEST_FILE.is_file() else {}
    cache_dir = Path(values.get("MODEL_CACHE_DIR") or ROOT / ".cache" / "models")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return ModelArtifacts(manifest, cache_dir, request)
