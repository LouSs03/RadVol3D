# Quickstart: validar la capa de servicios

Esta guía sirve para comprobar, de principio a fin, que la funcionalidad funciona. No incluye
la implementación. Los detalles están en [contracts/](contracts/) y en
[data-model.md](data-model.md).

Los comandos son para Git Bash, desde la raíz del repositorio y con el entorno virtual activo.

## 0. Requisitos

| Para | Hace falta |
|---|---|
| Bloques A y B (dobles) | Python 3.11 o superior y `pip install -e . -r requirements-dev.txt` |
| Bloque C (integración y concurrencia) | `.env.test` apuntando al Supabase de prueba (ver `.env.test.example`) |
| Bloque D (modelos reales) | `pip install -e ".[ml]"`, los archivos locales de `models/` (no versionados) y las variables `MODEL_BUCKET`, `EN1_WEIGHTS_OBJECT` y `EN2_WEIGHTS_OBJECT` en `.env` y `.env.test` |

En Linux, para no bajar la versión con CUDA:
`pip install -e ".[ml]" --extra-index-url https://download.pytorch.org/whl/cpu`.

## A. Lo que corre antes de cada commit (sin torch, sin red)

```bash
ruff check src tests
python scripts/check_naming_convention.py
pytest -m "unit or architecture"
```

**Resultado esperado:** todo en verde. Ninguna prueba `unit` importa torch. Para comprobarlo,
corre esto en un entorno sin el extra `ml`: las pruebas siguen pasando.

## B. Cobertura como la mide el CI

```bash
pytest -m unit --cov=src/radvol3d --cov-report=
coverage report --include="src/radvol3d/services/*" \
  --omit="*/en1_network.py,*/en1_reconstructor.py,*/lung_unet_network.py,*/lung_segmenter.py" \
  --fail-under=80
```

**Resultado esperado:** `services/` llega al 80 % o más, sin los cuatro módulos que solo
corren con torch (research.md R17).

## C. Tubería completa con dobles contra Supabase de prueba

```bash
pytest -m integration tests/integration/services -v
pytest -m concurrency tests/concurrency -v
```

**Resultado esperado:**

- **Historia 1.** Un estudio de pulmón termina en `completed`. Sus cuatro etapas están en
  `completed` y cada una tiene inicio y fin. La 2 y la 3 tienen modelo, y el resultado trae
  las cinco rutas.
- **Historia 2.** Una estrategia que falla en la etapa 3 deja la etapa 3 en `failed`, la 4 en
  `skipped` y el estudio en `failed`. `liver` lanza `ModelNotAvailableError` sin crear el
  estudio.
- **Historia 3.** Después de `delete_study`, pedir el estudio lanza `StudyNotFoundError` y no
  queda ninguna de sus diez rutas en el bucket.
- **SC-005.** En 20 repeticiones, dos estudios a la vez dan los mismos resultados que por
  separado.
- **Sin `.env.test`:** las pruebas se omiten con un mensaje, no fallan.

## D. Modelos reales (último bloque)

### D1. Preparar los artefactos (una sola vez, por quien tiene `models/`)

```bash
python scripts/export_en2_weights.py --checkpoint models/en2_pulmon_mejor.pth   --metrics models/metricas_test.json   --output .cache/models/segmentation_lung/1.0.0/weights.pth
python scripts/generate_regression_reference.py --models-dir models   --en2-weights .cache/models/segmentation_lung/1.0.0/weights.pth   --output-dir .cache/models
mkdir -p .cache/models/reconstruction_en1/1.0.0
cp "models/en1_pesos_liviano (2).pth" .cache/models/reconstruction_en1/1.0.0/weights.pth
python scripts/publish_model_artifacts.py --env-file .env.test   --en1-weights "models/en1_pesos_liviano (2).pth"   --en2-weights .cache/models/segmentation_lung/1.0.0/weights.pth   --regression-dir .cache/models/regression
```

`generate_regression_reference.py` tarda varios minutos (EN-2 corre dos veces con TTA). La
copia de EN-1 a `.cache/models/` deja la caché local con la misma estructura que el
bucket: así las pruebas `ml` no necesitan bajar nada.

**Resultado esperado:**

- el `.pth` exportado se abre con `torch.load(..., weights_only=True)`;
- `tests/ml/reference/manifest.json` queda con el SHA-256 de cada objeto;
- `git status` no muestra ningún `.pth` ni `.npy`.

### D2. Regresión y estudio de ejemplo

```bash
pytest -m ml -v
pytest -m ml --cov=src/radvol3d/services --cov-report=term-missing
```

**Resultado esperado:**

- **EN-1, caso del fantoma:** el volumen difiere de la referencia en menos de `1e-5`.
- **EN-2, casos 2 y 3:** la máscara es idéntica, la probabilidad difiere en menos de `1e-5`, y
  el resumen es igual campo por campo, salvo `study_code`, `organ`, `model_name` y
  `model_version`.
- **Estudio de ejemplo** (las proyecciones del fantoma pasadas por `StudyService` con las
  estrategias reales y la persistencia de prueba): devuelve volumen, máscara, probabilidad,
  resumen, `organ.glb` y `tumor.glb`. Las dos mallas empiezan con `glTF` y trimesh las vuelve
  a abrir.

Como referencia, en la laptop de desarrollo EN-1 tarda ≈ 11 s por estudio en CPU (autoprueba
original), y EN-2 ≈ 148 s con TTA. La suite `ml` tarda varios minutos.

El caso 4 de la regresión, el resumen por regiones sobre una máscara sintética, no usa torch.
Corre con `pytest -m unit`.

### D3. Arranque de la aplicación

```bash
uvicorn radvol3d.main:app
```

**Resultado esperado:**

- el registro de arranque dice qué modelos quedaron disponibles;
- la tabla `model` tiene `reconstruction_en1 1.0.0` y `segmentation_lung 1.0.0` con
  `trained_on` vacío;
- si `EN2_WEIGHTS_OBJECT` se borra del `.env`, la aplicación arranca igual y procesar un
  estudio de pulmón lanza `ModelNotAvailableError`.

## E. Cierre

```bash
pytest -m architecture
git status --short          # sin .pth, .npy ni archivos de models/
```
