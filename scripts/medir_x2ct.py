"""Mide X2CT-GAN en esta maquina: carga del modelo, reconstruccion por placa y RAM maxima.

Usa el mismo camino que el backend: baja los pesos del bucket de modelos (o los toma
de la cache), verifica su huella y carga el modelo en CPU con X2ctStrategy. Despues
reconstruye cada placa indicada y, al final, informa el pico de memoria del proceso.

Uso (en el servidor, con el .env del sistema):
    python scripts/medir_x2ct.py placa1.dcm placa2.dcm --repeticiones 3

Sin placas reconstruye una placa sintetica (solo comprueba el flujo y los tiempos).
"""

import argparse
import platform
import sys
import time
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from radvol3d.persistence.object_storage import ObjectStorage  # noqa: E402
from radvol3d.persistence.settings import (  # noqa: E402
    ModelSettings,
    RadiographEngineSettings,
    Settings,
)
from radvol3d.persistence.split_weights_store import SplitWeightsStore  # noqa: E402
from radvol3d.services.reconstruction.x2ct_strategy import (  # noqa: E402
    X2CT_WEIGHTS_OBJECT,
    X2CT_WEIGHTS_SHA256_PREFIX,
    X2ctStrategy,
)


def peak_memory_mb() -> float | None:
    """Pico de memoria residente del proceso, en MB (Linux y Windows)."""
    try:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return peak / 1024 if platform.system() == "Linux" else peak / (1024 * 1024)
    except ImportError:
        pass
    try:
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.K32GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        kernel32.K32GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        if not kernel32.K32GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            return None
        return counters.PeakWorkingSetSize / (1024 * 1024)
    except (AttributeError, OSError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("placas", nargs="*", type=Path, help="Radiografias DICOM")
    parser.add_argument("--repeticiones", type=int, default=1)
    parser.add_argument("--env-file", type=Path, default=REPOSITORY_ROOT / ".env")
    args = parser.parse_args(argv)

    settings = Settings(_env_file=args.env_file)
    model_settings = ModelSettings(_env_file=args.env_file)
    engine = RadiographEngineSettings(_env_file=args.env_file)
    object_path = engine.x2ct_weights_object or X2CT_WEIGHTS_OBJECT
    storage = ObjectStorage.from_settings(settings, bucket=model_settings.model_bucket)
    store = SplitWeightsStore(storage, model_settings.model_cache_dir)

    start = time.perf_counter()
    weights = store.fetch(object_path, X2CT_WEIGHTS_SHA256_PREFIX)
    elapsed = time.perf_counter() - start
    print(f"Pesos listos (bajados o de la cache, huella verificada): {elapsed:.1f} s")
    print(f"Memoria antes de cargar el modelo: {peak_memory_mb() or 0:.0f} MB")

    start = time.perf_counter()
    strategy = X2ctStrategy.from_weights(weights)
    print(f"Carga del modelo: {time.perf_counter() - start:.2f} s")

    entradas = [(placa.name, placa.read_bytes()) for placa in args.placas]
    if not entradas:
        print("Sin placas: se omite la reconstruccion (indique uno o mas .dcm).")
    for name, data in entradas:
        for repetition in range(args.repeticiones):
            start = time.perf_counter()
            result = strategy.reconstruct_study(data)
            elapsed = time.perf_counter() - start
            timings = result.metadata.get("tiempos_s", {})
            print(
                f"{name} #{repetition + 1}: {elapsed:.2f} s en total "
                f"(inferencia {timings.get('inferencia', '?')} s), voxel {result.voxel_mm}, "
                f"relativas={result.relative_measurements}"
            )
    peak = peak_memory_mb()
    print(f"RAM maxima del proceso: {peak:.0f} MB" if peak else "RAM maxima: no disponible")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
