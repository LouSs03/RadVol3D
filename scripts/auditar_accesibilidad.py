#!/usr/bin/env python3
"""A3: accesibilidad y usabilidad de RadVol3D segun ISO/IEC 25023.

Revisa la pagina desplegada y cuenta, por cada comprobacion, cuantos elementos
cumplen y cuantos no. Esa proporcion es la forma de medida que usa la 25023 para
accesibilidad y para proteccion frente a errores de usuario: elementos conformes
dividido entre elementos evaluados.

Las comprobaciones siguen las pautas WCAG 2.1 nivel AA, que es el criterio
publico que se suele usar para dar contenido a "accesible".

Lo que una revision automatica NO puede ver (navegacion solo con teclado, lector
de pantalla, claridad de los textos) queda listado al final como lista manual.

Uso (en tu PC, WSL):
    python3 scripts/auditar_accesibilidad.py
    python3 scripts/auditar_accesibilidad.py --archivo src/radvol3d/static/index.html

Deja el CSV en la carpeta evidencias/.
"""

import argparse
import csv
import re
import sys
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

CARPETA_SALIDA = Path("evidencias")
CONTRASTE_MINIMO = 4.5  # WCAG 2.1 AA para texto normal
DESACTIVADO = re.compile(r"\[disabled\]|:disabled|\.disabled|\.locked")

INTERACTIVOS = {"button", "a"}
CAMPOS = {"input", "select", "textarea"}
TIPOS_SIN_ETIQUETA = {"hidden", "submit", "button", "reset"}


class Elemento:
    def __init__(self, etiqueta: str, atributos: dict, linea: int):
        self.etiqueta = etiqueta
        self.atributos = atributos
        self.linea = linea
        self.texto = ""

    @property
    def nombre_accesible(self) -> str:
        """Lo que anunciaria un lector de pantalla."""
        for clave in ("aria-label", "title", "aria-labelledby"):
            if self.atributos.get(clave, "").strip():
                return self.atributos[clave].strip()
        return self.texto.strip()

    def __str__(self) -> str:
        identificador = self.atributos.get("id") or self.atributos.get("class") or ""
        return f"linea {self.linea:>5}  <{self.etiqueta}> {identificador}"[:88]


class LectorHtml(HTMLParser):
    """Recoge los elementos que nos interesan, con su linea y su texto."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elementos: list[Elemento] = []
        self.encabezados: list[tuple[int, int]] = []
        self.abiertos: list[Elemento] = []
        self.estilos: list[str] = []
        self.en_estilo = False
        self.html_lang = ""
        self.titulo = ""
        self.en_titulo = False

    def handle_starttag(self, etiqueta, atributos):
        mapa = {clave: (valor or "") for clave, valor in atributos}
        linea = self.getpos()[0]
        if etiqueta == "html":
            self.html_lang = mapa.get("lang", "")
        if etiqueta == "title":
            self.en_titulo = True
        if etiqueta == "style":
            self.en_estilo = True
        if etiqueta in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.encabezados.append((int(etiqueta[1]), linea))
        elemento = Elemento(etiqueta, mapa, linea)
        self.elementos.append(elemento)
        if etiqueta not in {"input", "img", "br", "hr", "meta", "link", "path", "circle", "rect"}:
            self.abiertos.append(elemento)

    def handle_endtag(self, etiqueta):
        if etiqueta == "title":
            self.en_titulo = False
        if etiqueta == "style":
            self.en_estilo = False
        for indice in range(len(self.abiertos) - 1, -1, -1):
            if self.abiertos[indice].etiqueta == etiqueta:
                del self.abiertos[indice:]
                return

    def handle_data(self, datos):
        if self.en_titulo:
            self.titulo += datos
        if self.en_estilo:
            self.estilos.append(datos)
            return
        for elemento in self.abiertos:
            elemento.texto += datos


# ---------------------------------------------------------------------------
# Contraste de color (WCAG 2.1)
# ---------------------------------------------------------------------------
def a_rgb(color: str) -> tuple[int, int, int] | None:
    color = color.strip()
    if re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        return tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))  # type: ignore[return-value]
    if re.fullmatch(r"#[0-9a-fA-F]{3}", color):
        return tuple(int(c * 2, 16) for c in color[1:])  # type: ignore[return-value]
    return None


def luminancia(rgb: tuple[int, int, int]) -> float:
    canales = []
    for valor in rgb:
        proporcion = valor / 255
        canales.append(
            proporcion / 12.92 if proporcion <= 0.04045 else ((proporcion + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * canales[0] + 0.7152 * canales[1] + 0.0722 * canales[2]


def contraste(frente: tuple[int, int, int], fondo: tuple[int, int, int]) -> float:
    claro, oscuro = sorted([luminancia(frente), luminancia(fondo)], reverse=True)
    return (claro + 0.05) / (oscuro + 0.05)


def variables_css(css: str) -> dict[str, str]:
    bloque = re.search(r":root\s*\{([^}]*)\}", css)
    if not bloque:
        return {}
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", bloque.group(1)))


def resolver(valor: str, variables: dict[str, str]) -> str:
    referencia = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", valor.strip())
    return variables.get(referencia.group(1), "").strip() if referencia else valor.strip()


def revisar_contraste(css: str) -> tuple[list[str], int, int]:
    """Busca reglas que fijan color y background juntos y mide su contraste."""
    variables = variables_css(css)
    fallos, evaluadas = [], 0
    for selector, cuerpo in re.findall(r"([^{}]+)\{([^}]*)\}", css):
        if DESACTIVADO.search(selector):
            continue  # WCAG 1.4.3 exime a los controles desactivados
        color = re.search(r"(?<![-\w])color\s*:\s*([^;]+)", cuerpo)
        fondo = re.search(r"background(?:-color)?\s*:\s*([^;]+)", cuerpo)
        if not (color and fondo):
            continue
        frente = a_rgb(resolver(color.group(1), variables))
        detras = a_rgb(resolver(fondo.group(1).split()[0], variables))
        if not (frente and detras):
            continue
        evaluadas += 1
        razon = contraste(frente, detras)
        if razon < CONTRASTE_MINIMO:
            fallos.append(
                f"{selector.strip()[:40]:<42} {razon:4.2f}:1  "
                f"(minimo {CONTRASTE_MINIMO})"
            )
    return fallos, evaluadas, evaluadas - len(fallos)


# ---------------------------------------------------------------------------
# Comprobaciones
# ---------------------------------------------------------------------------
def comprobar(lector: LectorHtml, css: str) -> list[dict]:
    resultados: list[dict] = []

    def anotar(clave, criterio, evaluados, conformes, hallazgos):
        resultados.append({
            "comprobacion": clave,
            "criterio_wcag": criterio,
            "evaluados": evaluados,
            "conformes": conformes,
            "proporcion": round(conformes / evaluados, 4) if evaluados else 1.0,
            "hallazgos": hallazgos,
        })

    anotar("Idioma declarado en la pagina", "3.1.1", 1, 1 if lector.html_lang else 0,
           [] if lector.html_lang else ["<html> sin atributo lang"])

    anotar("Titulo de la pagina", "2.4.2", 1, 1 if lector.titulo.strip() else 0,
           [] if lector.titulo.strip() else ["<title> vacio"])

    controles = [e for e in lector.elementos if e.etiqueta in INTERACTIVOS]
    sin_nombre = [e for e in controles if not e.nombre_accesible]
    anotar("Controles con nombre accesible", "4.1.2", len(controles),
           len(controles) - len(sin_nombre), [str(e) for e in sin_nombre])

    etiquetados = {
        e.atributos["for"] for e in lector.elementos
        if e.etiqueta == "label" and e.atributos.get("for")
    }
    campos = [
        e for e in lector.elementos
        if e.etiqueta in CAMPOS
        and e.atributos.get("type", "text") not in TIPOS_SIN_ETIQUETA
        and "hidden" not in e.atributos  # oculto: no llega al lector de pantalla
    ]
    sin_etiqueta = [
        e for e in campos
        if e.atributos.get("id") not in etiquetados
        and not e.atributos.get("aria-label")
        and not e.atributos.get("aria-labelledby")
    ]
    anotar("Campos con etiqueta asociada", "1.3.1 / 3.3.2", len(campos),
           len(campos) - len(sin_etiqueta), [str(e) for e in sin_etiqueta])

    lienzos = [e for e in lector.elementos if e.etiqueta == "canvas"]
    sin_alternativa = [
        e for e in lienzos
        if not e.atributos.get("aria-label")
        and not e.atributos.get("aria-labelledby")
        # aria-hidden es correcto cuando el dibujo solo repite lo que ya dice el texto
        and e.atributos.get("aria-hidden") != "true"
    ]
    anotar("Lienzos con alternativa textual", "1.1.1", len(lienzos),
           len(lienzos) - len(sin_alternativa), [str(e) for e in sin_alternativa])

    imagenes = [e for e in lector.elementos if e.etiqueta == "img"]
    sin_alt = [e for e in imagenes if "alt" not in e.atributos]
    anotar("Imagenes con texto alternativo", "1.1.1", len(imagenes),
           len(imagenes) - len(sin_alt), [str(e) for e in sin_alt])

    # Botones que se dibujan como opciones de un grupo (clase "opt") pero que no
    # declaran que son opciones: el lector de pantalla no dice cual esta elegida.
    opciones = [
        e for e in lector.elementos
        if e.etiqueta == "button" and "opt" in e.atributos.get("class", "").split()
    ]
    def anuncia_su_estado(elemento: Elemento) -> bool:
        rol = elemento.atributos.get("role")
        if rol in {"radio", "option"}:
            return "aria-checked" in elemento.atributos or "aria-selected" in elemento.atributos
        if rol == "tab":
            return "aria-selected" in elemento.atributos
        return False

    sin_rol = [e for e in opciones if not anuncia_su_estado(e)]
    anotar("Opciones anuncian cual esta elegida", "4.1.2", len(opciones),
           len(opciones) - len(sin_rol), [str(e) for e in sin_rol])

    regiones = [
        e for e in lector.elementos
        if e.atributos.get("aria-live") or e.atributos.get("role") in {"status", "alert"}
    ]
    anotar("Avisos de estado anunciados", "4.1.3", 1, 1 if regiones else 0,
           [] if regiones else ["La pagina no declara ninguna region de estado"])

    tiene_pausa = "prefers-reduced-motion" in css
    anotar("Respeta 'reducir movimiento'", "2.3.3", 1, 1 if tiene_pausa else 0,
           [] if tiene_pausa else
           ["El visor rota solo y el CSS no atiende prefers-reduced-motion"])

    tiene_foco = ":focus-visible" in css or ":focus" in css
    anotar("Foco del teclado visible", "2.4.7", 1, 1 if tiene_foco else 0,
           [] if tiene_foco else ["El CSS no define un estilo de foco"])

    saltos = []
    anterior = 0
    for nivel, linea in lector.encabezados:
        if anterior and nivel > anterior + 1:
            saltos.append(f"linea {linea:>5}  h{anterior} seguido de h{nivel}")
        anterior = nivel
    anotar("Encabezados sin saltos de nivel", "1.3.1", max(1, len(lector.encabezados)),
           max(1, len(lector.encabezados)) - len(saltos), saltos)

    fallos_contraste, evaluadas, conformes = revisar_contraste(css)
    anotar("Contraste de texto suficiente", "1.4.3", max(1, evaluadas),
           conformes if evaluadas else 1, fallos_contraste)

    return resultados


LISTA_MANUAL = [
    "Crear un estudio completo usando SOLO el teclado (Tab, Shift+Tab, Enter, Espacio).",
    "Comprobar que en todo momento se ve cual elemento tiene el foco.",
    "Subir las 4 proyecciones sin tocar el raton (boton 'Elegir archivos').",
    "Abrir el visor 3D con teclado y llegar a los controles de opacidad y cortes.",
    "Poner el navegador al 200% de zoom: nada debe quedar cortado ni superpuesto.",
    "Con NVDA (gratis, Windows): comprobar que al elegir modo u organo se anuncia el cambio.",
    "Con NVDA: comprobar que al terminar el procesamiento se anuncia que el estudio esta listo.",
    "Subir un archivo invalido y comprobar que el mensaje de error se lee y explica que hacer.",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="https://radvol3d.me/static/")
    parser.add_argument("--archivo", default=None, help="revisar un HTML local en vez de la URL")
    argumentos = parser.parse_args()

    if argumentos.archivo:
        origen = argumentos.archivo
        html = Path(argumentos.archivo).read_text(encoding="utf-8")
    else:
        origen = argumentos.url
        peticion = urllib.request.Request(
            argumentos.url, headers={"User-Agent": "radvol3d-medicion"}
        )
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            html = respuesta.read().decode("utf-8", "replace")

    lector = LectorHtml()
    lector.feed(html)
    css = "\n".join(lector.estilos)

    resultados = comprobar(lector, css)

    print(f"Pagina revisada: {origen}")
    print("Criterio: WCAG 2.1 nivel AA\n")
    print(f"{'comprobacion':<40}{'eval':>6}{'ok':>6}{'proporcion':>12}  estado")
    print("-" * 78)
    for fila in resultados:
        estado = "CUMPLE" if fila["proporcion"] == 1.0 else "NO CUMPLE"
        print(f"{fila['comprobacion']:<40}{fila['evaluados']:>6}{fila['conformes']:>6}"
              f"{fila['proporcion']:>12.2%}  {estado}")

    fallidas = [fila for fila in resultados if fila["proporcion"] < 1.0]
    if fallidas:
        print("\n" + "=" * 78)
        print("HALLAZGOS")
        print("=" * 78)
        for fila in fallidas:
            print(f"\n{fila['comprobacion']}  (WCAG {fila['criterio_wcag']})")
            for hallazgo in fila["hallazgos"][:12]:
                print(f"    {hallazgo}")
            if len(fila["hallazgos"]) > 12:
                print(f"    ... y {len(fila['hallazgos']) - 12} mas")

    evaluados = sum(fila["evaluados"] for fila in resultados)
    conformes = sum(fila["conformes"] for fila in resultados)
    print("\n" + "=" * 78)
    print("RESULTADO SEGUN ISO/IEC 25023 — ACCESIBILIDAD")
    print("=" * 78)
    superadas = len(resultados) - len(fallidas)
    print(f"\nComprobaciones superadas          {superadas} de {len(resultados)}")
    print(f"Elementos conformes               {conformes} de {evaluados}")
    print(f"Proporcion de accesibilidad       {conformes / evaluados:.2%}")

    print("\nFalta la parte manual (la automatica no la puede ver):")
    for numero, linea in enumerate(LISTA_MANUAL, 1):
        print(f"  {numero}. {linea}")

    CARPETA_SALIDA.mkdir(exist_ok=True)
    ruta = CARPETA_SALIDA / "accesibilidad.csv"
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(
            archivo,
            fieldnames=["comprobacion", "criterio_wcag", "evaluados", "conformes", "proporcion",
                        "hallazgos"],
        )
        escritor.writeheader()
        for fila in resultados:
            escritor.writerow({**fila, "hallazgos": " | ".join(fila["hallazgos"])})
    print(f"\nEvidencia: {ruta}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
