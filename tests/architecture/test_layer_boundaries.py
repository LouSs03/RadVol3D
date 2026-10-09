"""Verifica que ninguna capa se salte a otra.

Esta prueba existe antes que el codigo a proposito: asi nunca entra un import que
rompa la arquitectura. Si falla, se corrige el import, nunca la prueba.
"""

import ast
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2] / "src" / "radvol3d"

# Que capas del propio paquete puede importar cada capa.
CAPAS_PERMITIDAS: dict[str, set[str]] = {
    "domain": set(),
    "persistence": {"domain", "config"},
    "services": {"persistence", "domain", "config"},
    "api": {"services", "domain", "config"},
}

# Que librerias externas tiene prohibidas cada capa, y por que.
EXTERNOS_PROHIBIDOS: dict[str, set[str]] = {
    "domain": {"fastapi", "starlette", "psycopg", "supabase", "torch"},
    "persistence": {"fastapi", "starlette"},
    "services": {"fastapi", "starlette"},
    "api": {"psycopg", "supabase", "torch"},
}


def _modulos_importados(arbol: ast.AST, paquete: str) -> list[str]:
    """Devuelve los modulos que importa un archivo, con los relativos resueltos."""
    modulos: list[str] = []
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.extend(alias.name for alias in nodo.names)
        elif isinstance(nodo, ast.ImportFrom):
            if nodo.level == 0:
                if nodo.module:
                    modulos.append(nodo.module)
            else:
                partes = paquete.split(".")
                base = ".".join(partes[: len(partes) - nodo.level + 1])
                modulos.append(f"{base}.{nodo.module}" if nodo.module else base)
    return modulos


def _archivos_de_capa(capa: str) -> list[Path]:
    carpeta = RAIZ / capa
    if not carpeta.is_dir():
        return []
    return sorted(carpeta.rglob("*.py"))


def _paquete_de(ruta: Path) -> str:
    relativa = ruta.relative_to(RAIZ.parent).with_suffix("")
    partes = list(relativa.parts)
    if partes[-1] == "__init__":
        partes.pop()
    else:
        partes.pop()
    return ".".join(partes)


@pytest.mark.architecture
@pytest.mark.parametrize("capa", sorted(CAPAS_PERMITIDAS))
def test_una_capa_solo_importa_las_permitidas(capa: str) -> None:
    """Ninguna capa importa otra capa del paquete que no tenga permitida."""
    permitidas = CAPAS_PERMITIDAS[capa]
    infracciones: list[str] = []

    for archivo in _archivos_de_capa(capa):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for modulo in _modulos_importados(arbol, _paquete_de(archivo)):
            if not modulo.startswith("radvol3d"):
                continue
            partes = modulo.split(".")
            if len(partes) < 2:
                continue
            destino = partes[1]
            if destino == capa or destino in permitidas:
                continue
            infracciones.append(f"{archivo.name} importa {modulo}")

    assert not infracciones, (
        f"La capa '{capa}' solo puede importar {sorted(permitidas) or 'nada'}:\n  "
        + "\n  ".join(infracciones)
    )


@pytest.mark.architecture
@pytest.mark.parametrize("capa", sorted(EXTERNOS_PROHIBIDOS))
def test_una_capa_no_importa_librerias_prohibidas(capa: str) -> None:
    """La persistencia no sabe que existe una web; la presentacion, que existe una base."""
    prohibidas = EXTERNOS_PROHIBIDOS[capa]
    infracciones: list[str] = []

    for archivo in _archivos_de_capa(capa):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for modulo in _modulos_importados(arbol, _paquete_de(archivo)):
            raiz = modulo.split(".")[0]
            if raiz in prohibidas:
                infracciones.append(f"{archivo.name} importa {modulo}")

    assert not infracciones, (
        f"La capa '{capa}' no puede importar {sorted(prohibidas)}:\n  "
        + "\n  ".join(infracciones)
    )


@pytest.mark.architecture
def test_el_dominio_no_depende_de_nada_del_paquete() -> None:
    """El dominio es el piso: si dependiera de otra capa, habria un ciclo."""
    infracciones: list[str] = []
    for archivo in _archivos_de_capa("domain"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for modulo in _modulos_importados(arbol, _paquete_de(archivo)):
            if modulo.startswith("radvol3d") and ".domain" not in modulo:
                infracciones.append(f"{archivo.name} importa {modulo}")
    assert not infracciones, "El dominio no puede depender de otras capas:\n  " + "\n  ".join(
        infracciones
    )
