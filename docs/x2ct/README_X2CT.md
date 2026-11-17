# Modelo X2CT-GAN (1 vista) – especificación para el sistema RadVol3D

Este documento describe el modelo que se usa en el modo **"1 radiografía"** del sistema.
Reemplaza al servicio AXON en Colab + ngrok para ese modo. El modo de **4 proyecciones no cambia**.

## Archivos

| Archivo | Dónde va | Qué es |
|---|---|---|
| `x2ct_sistema.py` | `src/radvol3d/services/reconstruction/x2ct/` (única copia en el repositorio) | Adaptador: lee DICOM/imagen, preprocesa, ejecuta el modelo y escribe el paquete de salida. **Usar esta versión** (incluye el descarte de ventanas VOI que saturan la imagen). Único cambio respecto al original: el import de `x2ct_network` usa la ruta del paquete. |
| `x2ct_network.py` | `src/radvol3d/services/reconstruction/x2ct/`, junto a `x2ct_sistema.py` | Arquitectura PyTorch (no modificar). |
| `30_net_G.pth` | **Supabase Storage**, nunca en git: bucket `radvol3d-models`, `reconstruction_x2ct/1.0.0/weights.pth.part00`–`02` | Pesos de 1 vista, 118 MB, en 3 partes de 39,4 MB. SHA-256 (12 primeros): `9d9241a5062f`. |

El backend usa el modelo a través de `services/reconstruction/x2ct_strategy.py`; el despliegue
está en `DESPLIEGUE.md`.

**Ojo con el tamaño:** si el bucket de Supabase tiene límite de 50 MB por archivo, los pesos (118 MB) se suben
**en partes** (por ejemplo, 3 partes de < 45 MB: `30_net_G.pth.part00`, `.part01`, `.part02`) y el backend
las descarga, las une y verifica la huella SHA-256 antes de cargar el modelo. No convertir a fp16 ni recortar los pesos.

## Dependencias (servidor sin GPU)

```
torch      # versión CPU: pip install torch --index-url https://download.pytorch.org/whl/cpu
numpy
pillow
pydicom
nibabel
pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg   # solo para DICOM comprimidos
```
No se usa `torchvision` ni `matplotlib` en producción (matplotlib solo para `--verificar-orientacion`).

## Contrato de uso

```python
from radvol3d.services.reconstruction.x2ct.x2ct_sistema import ReconstructorX2CT
rec = ReconstructorX2CT("ruta/30_net_G.pth", dispositivo="cpu")   # cargar UNA vez al iniciar
meta = rec.reconstruir("placa.dcm", "carpeta_salida/")             # por cada estudio
```

- **Entrada:** una radiografía frontal de tórax (PA/AP) en `.dcm`, o `.png`/`.jpg`.
- **Salida en `carpeta_salida/`:**
  - `volumen.nii.gz`: TC reconstruida 128×128×128, **int16 en HU** (−1000 a 1000). El tamaño del vóxel está en la cabecera NIfTI.
  - `entrada_modelo_128.png` / `.npy`: la placa exacta que vio el modelo (para el panel de validación).
  - `metadatos.json`: tamaño original, mm por píxel, ventana aplicada o descartada, orden de ejes, tiempos, NCC de control y `avisos`.
- **Tiempos medidos:** carga del modelo ~1–5 s; inferencia en CPU ~3 s (laptop i7) a ~11 s (Colab CPU). Medir en el servidor.
- **Memoria:** estimar y medir el pico de RAM en el servidor (volumen 128³ con capas intermedias; del orden de 1–2 GB, sin confirmar).

## Convención de ejes del volumen (fija)

- **x (eje 0):** horizontal de la placa, izquierda → derecha de la imagen tal como se ve.
- **y (eje 1):** profundidad, anterior (0) → posterior.
- **z (eje 2):** vertical, pies (0) → cabeza. **Los cortes axiales son `vol[:, :, k]`**.
- Orientación verificada en 6 radiografías reales (el eje AP es el 0 en el volumen crudo del modelo).

## Milímetros

- Si el DICOM trae `PixelSpacing` o `ImagerPixelSpacing`, `voxel_mm` es real en x y z; la profundidad y se asume igual a x.
- Si no lo trae (frecuente), `voxel_mm = [1, 1, 1]` nominal y `metadatos.json` lo avisa: el visor debe mostrar
  **"medidas relativas (sin tamaño de píxel)"** en vez de centímetros.

## Validación ya realizada (T1)

En 4 radiografías originales de LIDC-IDRI: la reconstrucción corresponde a su placa (NCC 0,72–0,82; la propia
reconstrucción es la más parecida en 4 de 4 casos, 0,78 frente a 0,42 con otro paciente), está en la misma posición
(desplazamiento < 3 %) y sale ~10 % más corta en vertical (sesgo sistemático del modelo).
No reconstruye detalle interno fiable (nódulos): **en este modo no hay segmentación**.
