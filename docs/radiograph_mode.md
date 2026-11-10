# Modo de una radiografía

Segundo modo de entrada pedido por el profesor el 6 de noviembre de 2026: el usuario sube **una radiografía de tórax real (DICOM)** y el sistema reconstruye un volumen con el modelo AXON CoarseDiff de Lourdes. El modo de 4 proyecciones no cambia. Requisitos y contrato del servicio: guía de Lourdes del 7 de noviembre (`Guia_companero_modo_1_radiografia.docx`).

## Cómo encaja en el sistema

Un estudio de una radiografía es un **estudio más** (`study.input_mode = 'radiograph'`). Reutiliza las mismas cuatro etapas, el historial, la recuperación tras recargar la página (por el código del estudio) y el visor:

| Etapa | 4 proyecciones | 1 radiografía |
| --- | --- | --- |
| 1 | Apila las 4 `.npy` | Vuelve a validar el DICOM (marca `DICM`) |
| 2 | EN-1 en el servidor | Servicio externo AXON: `/health`, `POST /jobs`, consulta cada 5 s, descarga el `.nii.gz` |
| 3 | EN-2 | **Gancho** `PendingSegmentationStrategy`: no busca lesiones (requisito 8) |
| 4 | Mallas | Mallas (mismo código) |

El navegador nunca habla con el servicio externo: todo pasa por el backend, así la clave no sale del servidor.

### Flujo HTTP

1. `POST /studies` con `"input_mode": "radiograph"` (solo `organ: "lung"`).
2. `POST /studies/{código}/radiograph`, formulario multipart con el campo `file`.
3. `POST /studies/{código}/process`: revisa `/health` del servicio (5 s). Si no responde, **503** y el estudio sigue en `pending`. Si ya hay 3 radiografías procesándose, **429**.
4. `GET /studies/{código}/status`: en la etapa 2 trae `remote_state` (`queued` o `running`).
5. `GET /radiograph-mode`: si el modo está disponible ahora (lo usa la interfaz).

### Volumen del servicio → convenio del sistema

`services/reconstruction/nifti_volume.py`. Medido con los 4 volúmenes de ejemplo:

- La matriz afín del `.nii.gz` no sirve (es la de la plantilla MNI). Ejes del archivo: 0 = axial (0 = cabeza), 1 = izquierda-derecha (0 = derecha), 2 = adelante-atrás (0 = adelante). Se reordenan a R, A, S como espera el resto del sistema.
- Ventana: el servicio entrega [0, 1] = [−100, 900] HU; el sistema usa [−1000, 1000] HU → `0,45 + 0,5 × valor`. Con eso la malla del pulmón sale de 5,4 a 6,1 L en los 4 ejemplos.

Si el visor muestra el tórax mal orientado el día de la prueba, solo hay que cambiar `AXIS_ORDER` y `FLIPPED_AXES`.

## Puesta en marcha

1. **Base de datos (antes de desplegar el código):** correr `docs/database/schema/003_add_radiograph_input.sql` en el editor SQL de Supabase, primero en la base de prueba y después en la real.
2. **Variables** en el `.env` del servidor: `AXON_URL` y `AXON_API_KEY` (ver `.env.example`). Sin ellas el modo queda "no disponible" y lo demás funciona igual.
3. **Nginx:** el DICOM puede pesar hasta 50 MB → `client_max_body_size 55M;` en el sitio de RadVol3D.
4. `systemctl restart radvol3d`.

## Probar sin el servicio real

```bash
python scripts/axon_mock_server.py --volumes <carpeta con los .nii.gz de ejemplo> --key clave-de-prueba --step-seconds 5
# .env: AXON_URL=http://127.0.0.1:8765  AXON_API_KEY=clave-de-prueba  AXON_POLL_SECONDS=1
```

Modos del simulador: `ok`, `apagado` (página HTML de ngrok, ERR_NGROK_3200), `error`, `lento` y `perdido` (404). Se cambia sin reiniciar con `curl -X POST http://127.0.0.1:8765/mock/mode -d '{"mode":"apagado"}'`.

La prueba de orientación con los volúmenes reales se activa con `RADVOL3D_AXON_EXAMPLES=<carpeta> pytest tests/unit/services/test_nifti_volume.py`. Los volúmenes y DICOM de LIDC-IDRI **no van al repositorio** (licencia de TCIA).

## Decisiones tomadas (revisables en la reunión)

| Decisión de la guía (§10) | Lo que hace este cambio |
| --- | --- |
| ¿Solo DICOM o también PNG/JPG? | Solo DICOM (`.dcm`, `.dicom` o sin extensión), con la marca `DICM` revisada en el navegador y en el backend. |
| Tamaño máximo | 50 MB, no 60: el bucket gratuito de Supabase no acepta archivos de más de 50 MB. |
| Trabajos simultáneos | 3 radiografías en `processing` como máximo, para todo el sistema (no hay usuarios con sesión). |
| ¿Dónde vive el registro de trabajos? | En la tabla `study` de siempre (dos columnas nuevas). El `job_id` del servicio no se guarda: si Colab se reinicia, el estudio falla y se reintenta con uno nuevo. |
| Conservación de la radiografía y el volumen | Igual que los demás estudios: hasta que se borra el estudio. |
| Autenticación (requisito 9) | El sistema todavía no tiene usuarios con sesión: queda pendiente. |
| Anonimizar la cabecera DICOM | Pendiente como mejora (los DICOM de LIDC-IDRI ya están anonimizados). |
