# Contrato: historial de estudios (API HTTP)

Se suma a [../../004-rest-api-viewer/contracts/http_api.md](../../004-rest-api-viewer/contracts/http_api.md).
Las rutas existentes no cambian. El cuerpo de error es el mismo de 004, `{"detail": ...}`.
Un 422 de validación no devuelve el valor recibido.

Router nuevo: `src/radvol3d/api/routers/history_router.py`, con prefijo `/studies` y
etiqueta `historial`.

## `GET /studies` → 200

Lista todos los estudios, del más reciente al más antiguo.

Parámetros de consulta. Ninguno lleva datos personales:

| Parámetro | Tipo | Por defecto | Regla |
|---|---|---|---|
| `offset` | entero | `0` | ≥ 0 |
| `limit` | entero | `50` | entre 1 y 100 |

Respuesta, `StudyHistoryResponse`:

```json
{
  "items": [
    {
      "study_code": "RV-20261012-1530",
      "organ": "lung",
      "status": "completed",
      "created_at": "2026-10-12T15:30:04.120000Z",
      "lesion_count": 2,
      "total_lesion_volume_mm3": 1843.75,
      "national_id": "12345678"
    },
    {
      "study_code": "RV-20261012-1012",
      "organ": "lung",
      "status": "processing",
      "created_at": "2026-10-12T10:12:40.004000Z",
      "lesion_count": null,
      "total_lesion_volume_mm3": null,
      "national_id": null
    }
  ],
  "offset": 0,
  "limit": 50,
  "has_more": false
}
```

Los valores del ejemplo son ilustrativos: muestran la forma de la respuesta, no son
resultados de un modelo.

Reglas:

- `lesion_count` y `total_lesion_volume_mm3` son `null` salvo en `completed`. En `completed`
  sin lesiones valen `0` y `0.0`.
- `total_lesion_volume_mm3` está en mm³, como `volume_mm3` de `GET /studies/{code}/result`.
- `national_id` es `null` cuando el paciente no tiene DNI.
- Ninguna respuesta lleva `first_name` ni `last_name`.

Errores:

- **422**: `offset` o `limit` fuera de rango.
- **503**: base no disponible.

## `POST /studies/search` → 200

Lista los estudios del paciente con ese DNI. El DNI va en el cuerpo, nunca en la URL
(research.md R1).

Cuerpo (`application/json`), `StudySearchRequest`:

```json
{ "national_id": "12345678", "offset": 0, "limit": 50 }
```

- `national_id` es obligatorio y tiene exactamente ocho dígitos. Se quitan los espacios de
  los extremos.
- `offset` y `limit` siguen las mismas reglas que en `GET /studies`.

Respuesta: `StudyHistoryResponse`, con la misma forma y el mismo orden. Un DNI sin estudios
devuelve `items: []` y `has_more: false`, con código 200: no es un error.

Errores:

- **422**: `national_id` ausente o sin ocho dígitos, u `offset`/`limit` fuera de rango. El
  cuerpo sigue la forma de 004 (`loc`, `msg`, `type`), sin `input`: el DNI enviado no vuelve.
- **503**: base no disponible.

## Privacidad (FR-009 a FR-013)

- **Datos personales en las respuestas**: estas dos rutas son la única excepción a FR-029
  de 004, y solo para `national_id`. Las demás rutas siguen sin datos personales.
- **Registro de acceso**: el DNI no aparece en él. `GET /studies` no lo recibe, y
  `POST /studies/search` lo recibe en el cuerpo, que no se registra.
- **Página web**:
  - el DNI del filtro vive solo en memoria;
  - no va al hash de la URL, a `localStorage` ni a la consola;
  - la ruta de la vista sigue siendo `#/history`, sin parámetros.
