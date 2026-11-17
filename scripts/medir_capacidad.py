#!/usr/bin/env python3
"""A2: capacidad y escalabilidad de RadVol3D segun ISO/IEC 25023.

La capacidad es la subcaracteristica de rendimiento que mide cuanta carga aguanta
el sistema. Es la via para hablar de escalabilidad con metricas que si existen en
la 25023 (en la edicion 2023 de la 25010 la escalabilidad es subcaracteristica de
flexibilidad, pero la 25023 todavia no trae formulas para ella).

Lanza peticiones de SOLO LECTURA con 1, 2, 5, 10 y 20 usuarios simultaneos y mide:

  - Rendimiento de procesamiento: peticiones atendidas por segundo.
  - Tiempo de respuesta bajo carga: media y p95 en cada nivel.
  - Errores: cuantas peticiones no devolvieron 200.

El punto de saturacion es el nivel donde las peticiones por segundo dejan de subir
y el tiempo de respuesta empieza a crecer. Ese numero es la capacidad del sistema.

No crea, no modifica y no borra estudios. No manda a procesar nada.

ATENCION: no lo corras mientras alguien esta usando la pagina para una demo.

Uso (en tu PC, WSL):
    python3 scripts/medir_capacidad.py
    python3 scripts/medir_capacidad.py https://radvol3d.me --niveles 1,2,5,10,20

Deja el CSV en la carpeta evidencias/.
"""

import argparse
import csv
import statistics
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

RUTA_MEDIDA = "/studies?limit=20&offset=0"
PETICIONES_POR_NIVEL = 60
PAUSA_ENTRE_NIVELES_S = 5.0
CARPETA_SALIDA = Path("evidencias")


def una_peticion(url: str) -> tuple[float, bool]:
    """Devuelve (segundos, si salio bien)."""
    peticion = urllib.request.Request(url, headers={"User-Agent": "radvol3d-medicion"})
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(peticion, timeout=60) as respuesta:
            respuesta.read()
            bien = respuesta.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        bien = False
    return time.perf_counter() - inicio, bien


def medir_nivel(url: str, usuarios: int, peticiones: int) -> dict:
    """Lanza las peticiones con 'usuarios' hilos a la vez y mide el conjunto."""
    inicio = time.perf_counter()
    with ThreadPoolExecutor(max_workers=usuarios) as grupo:
        resultados = list(grupo.map(lambda _: una_peticion(url), range(peticiones)))
    duracion = time.perf_counter() - inicio

    tiempos = sorted(segundos for segundos, _ in resultados)
    errores = sum(1 for _, bien in resultados if not bien)
    posicion_p95 = max(0, round(0.95 * len(tiempos)) - 1)
    return {
        "usuarios": usuarios,
        "peticiones": peticiones,
        "duracion_s": round(duracion, 3),
        "peticiones_por_s": round(peticiones / duracion, 2),
        "media_ms": round(statistics.mean(tiempos) * 1000, 1),
        "p95_ms": round(tiempos[posicion_p95] * 1000, 1),
        "max_ms": round(tiempos[-1] * 1000, 1),
        "errores": errores,
        "tasa_exito": round((peticiones - errores) / peticiones, 4),
    }


def barra(valor: float, maximo: float, ancho: int = 28) -> str:
    if maximo <= 0:
        return ""
    return "#" * max(1, round(ancho * valor / maximo))


def guardar_csv(filas: list[dict]) -> Path:
    CARPETA_SALIDA.mkdir(exist_ok=True)
    ruta = CARPETA_SALIDA / "capacidad.csv"
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(filas[0]))
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", default="https://radvol3d.me")
    parser.add_argument("--niveles", default="1,2,5,10,20")
    parser.add_argument("--peticiones", type=int, default=PETICIONES_POR_NIVEL)
    argumentos = parser.parse_args()

    url = argumentos.base.rstrip("/") + RUTA_MEDIDA
    niveles = [int(n) for n in argumentos.niveles.split(",")]

    print(f"Sistema medido: {argumentos.base}")
    print(f"Peticion: GET {RUTA_MEDIDA}  (solo lectura)")
    print(f"Fecha: {datetime.now().isoformat(timespec='seconds')}\n")
    print(f"{'usuarios':>9} {'pet/s':>8} {'media':>9} {'p95':>9} {'errores':>8}")
    print("-" * 48)

    filas = []
    for indice, usuarios in enumerate(niveles):
        if indice:
            time.sleep(PAUSA_ENTRE_NIVELES_S)  # dejar respirar al servidor
        fila = medir_nivel(url, usuarios, argumentos.peticiones)
        filas.append(fila)
        print(
            f"{fila['usuarios']:>9} {fila['peticiones_por_s']:>8.2f} "
            f"{fila['media_ms']:>7.0f}ms {fila['p95_ms']:>7.0f}ms {fila['errores']:>8}"
        )

    print("\n" + "=" * 62)
    print("RESULTADO SEGUN ISO/IEC 25023 — CAPACIDAD")
    print("=" * 62)

    tope = max(filas, key=lambda fila: fila["peticiones_por_s"])
    maximo = tope["peticiones_por_s"]
    print("\nPeticiones por segundo segun usuarios simultaneos:\n")
    for fila in filas:
        print(f"  {fila['usuarios']:>3} usuarios  {fila['peticiones_por_s']:>7.2f}  "
              f"{barra(fila['peticiones_por_s'], maximo)}")

    print(f"\nRendimiento maximo de procesamiento   {maximo:7.2f} peticiones/s")
    print(f"  alcanzado con                       {tope['usuarios']:7d} usuarios simultaneos")

    base = filas[0]
    peor = filas[-1]
    print(f"\nTiempo de respuesta con 1 usuario     {base['media_ms']:7.0f} ms")
    print(f"Tiempo de respuesta con {peor['usuarios']:>2} usuarios   {peor['media_ms']:7.0f} ms")
    if base["media_ms"] > 0:
        print(f"  degradacion                         {peor['media_ms'] / base['media_ms']:7.2f}x")

    fallidos = [fila for fila in filas if fila["errores"]]
    if fallidos:
        print("\nNiveles con errores:")
        for fila in fallidos:
            print(f"  {fila['usuarios']:>3} usuarios  {fila['errores']} de {fila['peticiones']}"
                  f"   tasa de exito {fila['tasa_exito']:.2%}")
    else:
        print("\nSin errores en ningun nivel: el sistema atendio todas las peticiones.")

    print(f"\nEvidencia: {guardar_csv(filas)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
