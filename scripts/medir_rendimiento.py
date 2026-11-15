#!/usr/bin/env python3
"""A1: metricas de rendimiento de RadVol3D segun ISO/IEC 25023.

Mide dos cosas distintas que la norma separa dentro de "comportamiento temporal":

  - Tiempo medio de respuesta: cuanto tarda el servidor en contestar una peticion
    de lectura (la pagina, el historial, el estado del servicio).
  - Tiempo medio de ejecucion: cuanto tarda un estudio completo, de las cuatro
    etapas, desde que se manda a procesar hasta que queda listo.

De cada uno saca ademas su "adecuacion": el objetivo dividido entre lo medido.
Un valor de 1,00 o mas significa que el sistema cumple el objetivo.

Solo usa la API publica de lectura (GET). No crea, no modifica y no borra nada.
No lee ni guarda el nombre ni el DNI del paciente: solo el codigo del estudio.

Uso (en tu PC, WSL):
    python3 scripts/medir_rendimiento.py
    python3 scripts/medir_rendimiento.py https://radvol3d.me --repeticiones 30

Deja los CSV en la carpeta evidencias/.
"""

import argparse
import csv
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Objetivos. Cambialos por los del Project Charter si el profesor pide otros.
# ---------------------------------------------------------------------------
OBJETIVO_RESPUESTA_S = 1.0       # una peticion de lectura deberia contestar en 1 s
OBJETIVO_PROCESAMIENTO_S = 120.0  # un estudio completo deberia terminar en 2 min

# Peticiones de solo lectura que se miden. Nombre visible -> ruta.
ENDPOINTS = {
    "pagina_inicio": "/static/",
    "salud_api": "/health",
    "historial": "/studies?limit=20&offset=0",
    "modo_radiografia": "/radiograph-mode",
}

ETAPAS = {1: "preprocesamiento", 2: "reconstruccion", 3: "segmentacion", 4: "mallas"}

CARPETA_SALIDA = Path("evidencias")


def medir_una(base: str, ruta: str, tiempo_limite: float = 30.0) -> tuple[float, int]:
    """Devuelve (segundos que tardo, codigo HTTP). Mide hasta leer todo el cuerpo."""
    peticion = urllib.request.Request(base + ruta, headers={"User-Agent": "radvol3d-medicion"})
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(peticion, timeout=tiempo_limite) as respuesta:
            respuesta.read()
            codigo = respuesta.status
    except urllib.error.HTTPError as error:
        error.read()
        codigo = error.code
    return time.perf_counter() - inicio, codigo


def pedir_json(base: str, ruta: str) -> dict:
    peticion = urllib.request.Request(base + ruta, headers={"User-Agent": "radvol3d-medicion"})
    with urllib.request.urlopen(peticion, timeout=30) as respuesta:
        return json.load(respuesta)


def estadisticas(valores: list[float]) -> dict[str, float]:
    ordenados = sorted(valores)
    posicion_p95 = max(0, round(0.95 * len(ordenados)) - 1)
    return {
        "muestras": len(ordenados),
        "media_s": statistics.mean(ordenados),
        "mediana_s": statistics.median(ordenados),
        "p95_s": ordenados[posicion_p95],
        "desviacion_s": statistics.stdev(ordenados) if len(ordenados) > 1 else 0.0,
        "min_s": ordenados[0],
        "max_s": ordenados[-1],
    }


def medir_respuesta(base: str, repeticiones: int) -> list[dict]:
    """Tiempo medio de respuesta de cada peticion de lectura."""
    filas = []
    for nombre, ruta in ENDPOINTS.items():
        try:
            medir_una(base, ruta)  # calentamiento: no se cuenta
        except Exception as error:  # noqa: BLE001
            print(f"  {nombre:<20} no responde: {type(error).__name__}")
            continue
        tiempos, codigos = [], set()
        for _ in range(repeticiones):
            segundos, codigo = medir_una(base, ruta)
            tiempos.append(segundos)
            codigos.add(codigo)
            time.sleep(0.2)  # no saturar el servidor
        fila = {"peticion": nombre, "ruta": ruta, "http": ",".join(map(str, sorted(codigos)))}
        fila.update(estadisticas(tiempos))
        fila["adecuacion"] = OBJETIVO_RESPUESTA_S / fila["media_s"]
        filas.append(fila)
        print(
            f"  {nombre:<20} media {fila['media_s'] * 1000:7.1f} ms   "
            f"p95 {fila['p95_s'] * 1000:7.1f} ms   HTTP {fila['http']}"
        )
    return filas


def codigos_completados(base: str) -> list[dict]:
    """Estudios completados, del mas reciente al mas antiguo."""
    estudios, offset = [], 0
    while True:
        pagina = pedir_json(base, f"/studies?limit=100&offset={offset}")
        estudios += [item for item in pagina["items"] if item["status"] == "completed"]
        if not pagina.get("has_more"):
            return estudios
        offset += pagina["limit"]


def segundos_entre(inicio: str | None, fin: str | None) -> float | None:
    if not inicio or not fin:
        return None
    return (datetime.fromisoformat(fin) - datetime.fromisoformat(inicio)).total_seconds()


def medir_procesamiento(base: str, cuantos: int, modo: str | None) -> list[dict]:
    """Tiempo de ejecucion de los estudios ya completados que hay en el historial.

    El listado del historial no trae el modo de entrada, asi que el filtro por modo
    se aplica sobre la respuesta de estado de cada estudio, que si lo trae.
    """
    filas = []
    for estudio in codigos_completados(base):
        if len(filas) >= cuantos:
            break
        estado = pedir_json(base, f"/studies/{estudio['study_code']}/status")
        if modo and estado.get("input_mode", "projections") != modo:
            continue
        fila = {
            "study_code": estado["study_code"],
            "organo": estado.get("organ"),
            "modo": estado.get("input_mode", "projections"),
            "modelo": estado.get("reconstruction_model") or "-",
            "total_s": estado.get("total_time_sec"),
        }
        for etapa in estado.get("stages", []):
            nombre = ETAPAS.get(etapa["stage_number"], str(etapa["stage_number"]))
            fila[f"{nombre}_s"] = segundos_entre(etapa["started_at"], etapa["finished_at"])
        filas.append(fila)
        print(
            f"  {fila['study_code']:<22} {fila['modo']:<12} "
            f"{fila['total_s'] if fila['total_s'] is not None else '-':>8} s"
        )
    return filas


def guardar_csv(nombre: str, filas: list[dict]) -> Path:
    CARPETA_SALIDA.mkdir(exist_ok=True)
    ruta = CARPETA_SALIDA / nombre
    columnas: list[str] = []
    for fila in filas:
        for clave in fila:
            if clave not in columnas:
                columnas.append(clave)
    with ruta.open("w", newline="", encoding="utf-8") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=columnas)
        escritor.writeheader()
        escritor.writerows(filas)
    return ruta


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", default="https://radvol3d.me")
    parser.add_argument("--repeticiones", type=int, default=30)
    parser.add_argument("--ultimos", type=int, default=10)
    parser.add_argument("--modo", choices=["projections", "radiograph"], default=None)
    argumentos = parser.parse_args()
    base = argumentos.base.rstrip("/")

    print(f"Sistema medido: {base}")
    print(f"Fecha: {datetime.now().isoformat(timespec='seconds')}\n")

    print(f"TIEMPO DE RESPUESTA  ({argumentos.repeticiones} peticiones por ruta)")
    filas_respuesta = medir_respuesta(base, argumentos.repeticiones)
    if not filas_respuesta:
        print("\nNingun endpoint respondio. Revisa la direccion.")
        return 1

    print(f"\nTIEMPO DE EJECUCION  (ultimos {argumentos.ultimos} estudios completados)")
    filas_procesamiento = medir_procesamiento(base, argumentos.ultimos, argumentos.modo)
    if not filas_procesamiento:
        print("  No hay estudios completados todavia: procesa algunos y vuelve a correrlo.")

    print("\n" + "=" * 78)
    print("RESULTADO SEGUN ISO/IEC 25023")
    print("=" * 78)

    peor = max(filas_respuesta, key=lambda fila: fila["media_s"])
    media_global = statistics.mean([fila["media_s"] for fila in filas_respuesta])
    print(f"\nTiempo medio de respuesta       {media_global * 1000:8.1f} ms")
    print(f"  objetivo                      {OBJETIVO_RESPUESTA_S * 1000:8.1f} ms")
    print(f"  adecuacion (objetivo/medido)  {OBJETIVO_RESPUESTA_S / media_global:8.2f}"
          f"   {'CUMPLE' if media_global <= OBJETIVO_RESPUESTA_S else 'NO CUMPLE'}")
    print(f"  ruta mas lenta                {peor['peticion']} ({peor['media_s'] * 1000:.1f} ms)")

    totales = [fila["total_s"] for fila in filas_procesamiento if fila.get("total_s")]
    if totales:
        resumen = estadisticas(totales)
        print(f"\nTiempo medio de ejecucion       {resumen['media_s']:8.2f} s")
        print(f"  objetivo                      {OBJETIVO_PROCESAMIENTO_S:8.2f} s")
        print(f"  adecuacion (objetivo/medido)  "
              f"{OBJETIVO_PROCESAMIENTO_S / resumen['media_s']:8.2f}"
              f"   {'CUMPLE' if resumen['media_s'] <= OBJETIVO_PROCESAMIENTO_S else 'NO CUMPLE'}")
        print(f"  p95                           {resumen['p95_s']:8.2f} s")
        print(f"  muestras                      {resumen['muestras']:8d}")

    ruta_1 = guardar_csv("rendimiento_respuesta.csv", filas_respuesta)
    print(f"\nEvidencia: {ruta_1}")
    if filas_procesamiento:
        print(f"Evidencia: {guardar_csv('rendimiento_procesamiento.csv', filas_procesamiento)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
