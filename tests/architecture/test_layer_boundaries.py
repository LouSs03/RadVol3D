"""Verifica que ninguna capa se salte a otra.

Esta prueba existe antes que el codigo a proposito: asi nunca entra un import que
rompa la arquitectura. Si falla, se corrige el import, nunca la prueba.
"""

import ast
from pathlib import Path

import pytest

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "src" / "radvol3d"

# Que capas del propio paquete puede importar cada capa.
ALLOWED_LAYERS: dict[str, set[str]] = {
    "domain": set(),
    "persistence": {"domain", "config"},
    "services": {"persistence", "domain", "config"},
    "api": {"services", "domain", "config"},
}

# Que librerias externas tiene prohibidas cada capa, y por que.
FORBIDDEN_EXTERNAL_LIBRARIES: dict[str, set[str]] = {
    "domain": {"fastapi", "starlette", "psycopg", "supabase", "torch"},
    "persistence": {"fastapi", "starlette"},
    "services": {"fastapi", "starlette"},
    "api": {"psycopg", "psycopg_pool", "storage3", "supabase", "torch"},
}


def _imported_modules(tree: ast.AST, package: str) -> list[str]:
    """Devuelve los modulos que importa un archivo, con los relativos resueltos."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    modules.append(node.module)
            else:
                parts = package.split(".")
                base = ".".join(parts[: len(parts) - node.level + 1])
                modules.append(f"{base}.{node.module}" if node.module else base)
    return modules


def _layer_files(layer: str) -> list[Path]:
    folder = PACKAGE_ROOT / layer
    if not folder.is_dir():
        return []
    return sorted(folder.rglob("*.py"))


def _package_of(path: Path) -> str:
    relative = path.relative_to(PACKAGE_ROOT.parent).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    else:
        parts.pop()
    return ".".join(parts)


@pytest.mark.architecture
@pytest.mark.parametrize("layer", sorted(ALLOWED_LAYERS))
def test_a_layer_only_imports_the_allowed_layers(layer: str) -> None:
    """Ninguna capa importa otra capa del paquete que no tenga permitida."""
    allowed = ALLOWED_LAYERS[layer]
    violations: list[str] = []

    for file in _layer_files(layer):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for module in _imported_modules(tree, _package_of(file)):
            if not module.startswith("radvol3d"):
                continue
            parts = module.split(".")
            if len(parts) < 2:
                continue
            target = parts[1]
            if target == layer or target in allowed:
                continue
            violations.append(f"{file.name} importa {module}")

    assert not violations, (
        f"La capa '{layer}' solo puede importar {sorted(allowed) or 'nada'}:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.architecture
@pytest.mark.parametrize("layer", sorted(FORBIDDEN_EXTERNAL_LIBRARIES))
def test_a_layer_does_not_import_forbidden_libraries(layer: str) -> None:
    """La persistencia no sabe que existe una web; la presentacion, que existe una base."""
    forbidden = FORBIDDEN_EXTERNAL_LIBRARIES[layer]
    violations: list[str] = []

    for file in _layer_files(layer):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for module in _imported_modules(tree, _package_of(file)):
            root = module.split(".")[0]
            if root in forbidden:
                violations.append(f"{file.name} importa {module}")

    assert not violations, (
        f"La capa '{layer}' no puede importar {sorted(forbidden)}:\n  "
        + "\n  ".join(violations)
    )


@pytest.mark.architecture
def test_the_domain_does_not_depend_on_anything_in_the_package() -> None:
    """El dominio es el piso: si dependiera de otra capa, habria un ciclo."""
    violations: list[str] = []
    for file in _layer_files("domain"):
        tree = ast.parse(file.read_text(encoding="utf-8"))
        for module in _imported_modules(tree, _package_of(file)):
            if module.startswith("radvol3d") and ".domain" not in module:
                violations.append(f"{file.name} importa {module}")
    assert not violations, "El dominio no puede depender de otras capas:\n  " + "\n  ".join(
        violations
    )
