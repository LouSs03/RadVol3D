# Despliegue de X2CT-GAN (modo "1 radiografía") en el servidor

X2CT-GAN reemplaza al servicio AXON (Colab + ngrok) en el modo de una radiografía. Corre en
la CPU del servidor, dentro del mismo proceso de uvicorn. El modo de 4 proyecciones no cambia.

El código del modelo está en `src/radvol3d/services/reconstruction/x2ct/` (`x2ct_sistema.py` y
`x2ct_network.py`, única copia en el repositorio) y lo usa `x2ct_strategy.py`. Los pesos no están
en el repositorio ni en el servidor de antemano: el backend los baja de Supabase al arrancar.

## Qué necesita el servidor

| | |
|---|---|
| RAM | El proceso llegó a **~1,6 GB** con el modelo cargado, en una laptop. Sumarlo a lo que ya usan EN-1 y EN-2. Medir en el servidor (abajo). |
| Disco | ~120 MB más en la caché de modelos (`MODEL_CACHE_DIR`, por omisión `.cache/models`). |
| Python | Las mismas dependencias de siempre, más `pydicom`, `nibabel` y `pillow` (extra `ml`). |
| torch | Versión **solo CPU**. Sin `torchvision`. |

## Pasos

1. **Código.** Actualizar el repositorio en el servidor (`git pull` de `main` cuando el PR esté
   integrado).

2. **Dependencias** (con el entorno virtual del servicio activado):

   ```bash
   pip install torch --index-url https://download.pytorch.org/whl/cpu   # si torch no está, o es la versión con CUDA
   pip install -e ".[ml]"                                                # agrega pydicom, nibabel y pillow
   # Solo si llegan DICOM comprimidos (JPEG / JPEG 2000):
   # pip install pylibjpeg pylibjpeg-libjpeg pylibjpeg-openjpeg
   ```

3. **Variables** en el `.env` del servidor:

   ```
   RADIOGRAPH_ENGINE=x2ct
   X2CT_WEIGHTS_OBJECT=reconstruction_x2ct/1.0.0/weights.pth
   ```

   `MODEL_BUCKET` y las credenciales de Supabase son las de siempre. `AXON_URL` y `AXON_API_KEY`
   pueden quedar: con `x2ct` no se usan.

4. **Reiniciar** el servicio: `sudo systemctl restart radvol3d`.

   Al arrancar, el backend baja de Supabase las tres partes de los pesos
   (`weights.pth.part00`–`02`), las une, comprueba que el SHA-256 empiece por `9d9241a5062f` y
   guarda el archivo unido en la caché. Los arranques siguientes usan la caché (unos 0,3 s para
   volver a comprobar la huella). Si la huella no coincide o faltan partes, el modo de una
   radiografía queda "no disponible" y el resto del sistema arranca igual.

5. **Comprobar:**

   ```bash
   curl -s http://127.0.0.1:8000/radiograph-mode    # {"available": true, ...}
   journalctl -u radvol3d -n 50 | grep -i x2ct      # "X2CT-GAN cargado en ... s (pesos 9d9241a5062f)"
   ```

   Después, un estudio de prueba desde la interfaz: Nuevo estudio → 1 radiografía → subir un DICOM
   de tórax frontal → Procesar. Deben verse tres etapas (carga y validación, reconstrucción 3D,
   visualización) y el visor de una radiografía.

6. **Medir** carga, tiempo por placa y RAM máxima en el servidor:

   ```bash
   python scripts/medir_x2ct.py placa1.dcm placa2.dcm --repeticiones 3
   ```

   Usa el mismo camino que el backend (pesos desde Supabase o la caché) y no toca la base.

## Volver a AXON

`RADIOGRAPH_ENGINE=axon` en el `.env` y reiniciar. Se vuelve a usar el servicio de Colab con
`AXON_URL` y `AXON_API_KEY`, sin cambios de código.

## Nginx

Sin cambios: el límite de subida de 55 MB que ya pide el modo de una radiografía alcanza.

## Qué se guarda de cada estudio

En el bucket del estudio (además de `volume.npy` y `meshes/organ.glb`, como siempre):

```
<código>/reconstruction/volumen.nii.gz          volumen de X2CT en HU, con el vóxel en la cabecera
<código>/reconstruction/entrada_modelo_128.png  la placa exacta que vio el modelo
<código>/reconstruction/metadatos.json          lo que informa X2CT (mm por píxel, avisos, tiempos)
<código>/reconstruction/visor.json              vóxel con que se muestra y avisos
```

Borrar el estudio borra también estos archivos.
