# Contrato: API HTTP de RadVol3D

Es el contrato público de esta funcionalidad. Los esquemas están en
[data-model.md](../data-model.md) §5. La documentación interactiva (`/docs`) se genera de
los mismos esquemas y no puede contradecir este archivo.

Reglas comunes:

- `{code}` es el código del estudio: `^[A-Za-z0-9_-]{1,64}$`. Otro formato → 400.
- Un estudio inexistente → 404 en todas las rutas que llevan `{code}`.
- Errores: cuerpo `{"detail": "<mensaje en español>"}`. Validación de la entrada (422 de
  FastAPI): `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`, sin `input`.
- Ninguna respuesta trae nombre, apellido ni DNI del paciente.
- La tabla completa de errores está en [research.md](../research.md) R8.

---

## Estudios (`study_router.py`)

### `POST /studies` → 201

Crea un estudio `pending` sin proyecciones.

Cuerpo (`application/json`), `StudyCreate`:

```json
{
  "study_code": "lung_028",
  "organ": "lung",
  "patient": {"first_name": "Ana", "last_name": "Quispe", "national_id": "12345678"}
}
```

`patient` es opcional, y cada uno de sus campos también.

Respuesta, `StudyResponse`:

```json
{"study_code": "lung_028", "organ": "lung", "status": "pending",
 "created_at": "2026-10-09T15:04:05Z", "patient_code": "PAC000001"}
```

`Location: /studies/lung_028/status`.

| Caso | Código |
|---|---|
| código ya usado | 409 |
| código con formato inválido en el cuerpo | 422 (validación del esquema; en la ruta, un código inválido da 400) |
| órgano fuera de `lung`/`liver`, o datos del paciente inválidos | 422 |
| órgano sin modelo disponible (`liver`, o pesos ausentes) | 503 |

### `GET /studies/{code}/status` → 200

`StudyStatusResponse`:

```json
{"study_code": "lung_028", "organ": "lung", "status": "processing",
 "created_at": "2026-10-09T15:04:05Z", "patient_code": "PAC000001", "total_time_sec": null,
 "stages": [
   {"stage_number": 1, "stage_name": "preprocessing", "status": "completed",
    "started_at": "2026-10-09T15:05:00Z", "finished_at": "2026-10-09T15:05:00Z"},
   {"stage_number": 2, "stage_name": "reconstruction", "status": "running",
    "started_at": "2026-10-09T15:05:00Z", "finished_at": null},
   {"stage_number": 3, "stage_name": "segmentation", "status": "waiting",
    "started_at": null, "finished_at": null},
   {"stage_number": 4, "stage_name": "meshing", "status": "waiting",
    "started_at": null, "finished_at": null}
 ]}
```

Los valores de fecha son un ejemplo de forma, no datos reales.

### `POST /studies/{code}/process` → 202

Sin cuerpo. Reclama el estudio, lo pasa a `processing` y lanza la tubería en segundo plano.
Responde sin esperarla.

```json
{"study_code": "lung_028", "status": "processing", "status_url": "/studies/lung_028/status"}
```

| Caso | Código |
|---|---|
| no está `pending`, o no tiene sus cuatro proyecciones, o ya lo reclamó otro pedido | 409 |
| no hay modelo para su órgano | 503 (el estudio sigue `pending`) |

Un fallo de la tubería no cambia esta respuesta: se ve después en `GET /status`.

### `DELETE /studies/{code}` → 204

Sin cuerpo. Borra filas y archivos, incluidas las mallas por lesión. El paciente se
conserva.

| Caso | Código |
|---|---|
| estudio en `processing` | 409 |

---

## Proyecciones (`projection_router.py`)

### `POST /studies/{code}/projections` → 201

`multipart/form-data` con cuatro campos de archivo obligatorios: `angle_000`, `angle_045`,
`angle_090`, `angle_135`. El ángulo sale del nombre del campo.

Cada archivo: `.npy` numérico (sin objetos serializados), forma 128 × 128, valores finitos,
en el convenio de TA-2. Tamaño máximo por archivo: `config.MAX_PROJECTION_BYTES` (1 MiB).

Respuesta, `ProjectionsUploaded`:

```json
{"study_code": "lung_028", "angles": [0, 45, 90, 135]}
```

| Caso | Código |
|---|---|
| falta un campo | 422 (validación de FastAPI, sin `input`) |
| un archivo inválido (formato, forma, valores) | 422, el mensaje nombra el ángulo; no se guarda ninguno |
| un archivo mayor que el límite | 413, el mensaje nombra el ángulo y el límite |
| el estudio ya tiene proyecciones o no está `pending` | 409 |

---

## Resultados (`result_router.py`)

Todas estas rutas exigen el estudio en `completed`; si no, 409 con el estado actual en el
mensaje.

### `GET /studies/{code}/result` → 200

`ResultResponse`:

```json
{"study_code": "lung_028",
 "organ_mesh_url": "/studies/lung_028/result/organ.glb",
 "tumor_mesh_url": "/studies/lung_028/result/tumor.glb",
 "volume_url": "/studies/lung_028/result/volume.npy",
 "lesions": [
   {"lesion_number": 1, "organ": "lung",
    "location": "medio del eje 0 · medio del eje 1 · medio del eje 2",
    "volume_mm3": 8000.0, "max_diameter_mm": 34.64, "confidence": 0.9,
    "mesh_url": "/studies/lung_028/result/lesions/1.glb"}
 ]}
```

Los valores de la lesión son los del doble `FakeSegmentationStrategy`, no un resultado
clínico. `lesions` puede ser `[]`.

### Descargas

| Ruta | Tipo de contenido | Notas |
|---|---|---|
| `GET /studies/{code}/result/organ.glb` | `model/gltf-binary` | |
| `GET /studies/{code}/result/tumor.glb` | `model/gltf-binary` | todas las lesiones juntas |
| `GET /studies/{code}/result/volume.npy` | `application/octet-stream` | `Content-Disposition: attachment; filename="<code>_volume.npy"` |
| `GET /studies/{code}/result/lesions/{n}.glb` | `model/gltf-binary` | `n` desde 1; fuera de rango → 404 |

Un archivo que falta en el bucket → 404.

---

## Visor (`viewer_router.py`)

### `GET /viewer/{code}` → 200 (`text/html`)

Devuelve `web/viewer.html`. Si el estudio no existe, la misma página con 404. La página:

1. lee `{code}` de su URL y pide `GET /studies/{code}/status`;
2. en `pending` o `processing`, muestra el estado y lo vuelve a pedir cada 5 s;
3. en `failed`, muestra la etapa que falló;
4. en `completed`, pide `GET /studies/{code}/result`, carga `organ_mesh_url` y cada
   `mesh_url`, y arma la escena: órgano semitransparente (gris claro, opacidad 0,3), cada
   lesión opaca en su color de la paleta;
5. muestra la lista de lesiones con el color de cada una, el órgano, la ubicación, el
   volumen, el diámetro y la confianza, y un enlace a su `.glb`. Elegir una fila resalta su
   malla;
6. permite rotar (arrastrar), acercar (rueda), desplazar (botón derecho) y volver a la vista
   inicial (botón);
7. sin WebGL, muestra un aviso y los enlaces de descarga.

### Archivos estáticos

`/css/main.css`, `/js/viewer_3d.js` y `/js/viewer_state.js` los sirve el montaje de
`StaticFiles` que ya existe en `main.py`. Three.js llega por `importmap` desde
`cdn.jsdelivr.net`, con versión fija.
