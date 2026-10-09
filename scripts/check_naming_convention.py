#!/usr/bin/env python3
"""Verifica que no haya camelCase donde el equipo acordo snake_case.

En Python esto ya lo cubre ruff con las reglas N de PEP 8, asi que aqui se revisa
lo que ruff no ve: los nombres de archivos y carpetas, y el JavaScript de la
interfaz.

Nota: en Python las clases llevan PascalCase por la PEP 8. Eso no es mezclar
convenciones, y por eso no se marca.

Uso:
    python scripts/check_naming_convention.py
"""

import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

CARPETAS_REVISADAS = ("src", "tests", "scripts", "docs")
EXTENSIONES_REVISADAS = {".py", ".js", ".css", ".sql", ".md", ".html"}

# Carpetas que no son del proyecto: entornos virtuales, dependencias y cache.
# Se descarta cualquier ruta que tenga uno de estos nombres entre sus carpetas.
EXCLUDED_PARTS = frozenset(
    {".venv", "venv", "node_modules", "site-packages", ".git", "__pycache__"}
)

# Declaraciones de JavaScript: function, let, const, var y metodos de clase.
DECLARACION_JS = re.compile(r"\b(?:function|let|const|var)\s+([A-Za-z_$][\w$]*)")

TIENE_MAYUSCULA_INTERNA = re.compile(r"^[a-z_$][\w$]*[A-Z]")


def is_excluded(ruta: Path) -> bool:
    """True si la ruta pasa por una carpeta que no es del proyecto (EXCLUDED_PARTS).

    Se mira la ruta relativa a la raiz, para que el repositorio no quede excluido
    entero si vive dentro de una carpeta que se llame, por ejemplo, "venv".
    """
    return not EXCLUDED_PARTS.isdisjoint(ruta.relative_to(RAIZ).parts)


def revisar_nombres_de_archivo() -> list[str]:
    """Un nombre de archivo o carpeta con mayuscula interna rompe la convencion."""
    problemas: list[str] = []
    for carpeta in CARPETAS_REVISADAS:
        base = RAIZ / carpeta
        if not base.is_dir():
            continue
        for ruta in base.rglob("*"):
            if is_excluded(ruta) or ruta.name.startswith("."):
                continue
            if ruta.is_file() and ruta.suffix not in EXTENSIONES_REVISADAS:
                continue
            nombre = ruta.stem if ruta.is_file() else ruta.name
            if nombre.upper() == nombre:        # README, CONTRIBUTING
                continue
            if TIENE_MAYUSCULA_INTERNA.match(nombre):
                problemas.append(f"{ruta.relative_to(RAIZ)}: use snake_case")
    return problemas


def revisar_javascript() -> list[str]:
    """Variables y funciones de JavaScript en camelCase."""
    problemas: list[str] = []
    for ruta in RAIZ.rglob("*.js"):
        if is_excluded(ruta):
            continue
        for numero, linea in enumerate(ruta.read_text(encoding="utf-8").splitlines(), 1):
            for nombre in DECLARACION_JS.findall(linea):
                if nombre.upper() == nombre:     # MAX_SIZE
                    continue
                if nombre[0].isupper():          # una clase
                    continue
                if TIENE_MAYUSCULA_INTERNA.match(nombre):
                    problemas.append(
                        f"{ruta.relative_to(RAIZ)}:{numero}: '{nombre}' use snake_case"
                    )
    return problemas


def main() -> int:
    problemas = revisar_nombres_de_archivo() + revisar_javascript()
    if problemas:
        print("Convencion de nombres incumplida (%d):\n" % len(problemas))
        for problema in problemas:
            print("  -", problema)
        print("\nEl equipo acordo snake_case. Ver docs/standards/code_style.md")
        return 1
    print("Convencion de nombres: correcta.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
