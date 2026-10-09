# Quickstart: validar la API REST y el visor 3D

Guía para comprobar que la funcionalidad funciona de punta a punta. Las rutas y las formas
de las respuestas están en [contracts/http_api.md](contracts/http_api.md); aquí no se
repiten.

## Requisitos

- El entorno del proyecto (`.venv`) con `pip install -e .` y `-r requirements-dev.txt`.
- Node 22 o más nuevo, solo para las pruebas del visor.
- Para los pasos con base: `.env` (o `.env.test`) apuntando a un Supabase con
  `001_create_tables.sql` **y** `002_add_lesion_organ.sql` aplicados.
- Un navegador con WebGL y acceso a `cdn.jsdelivr.net` para el visor.
- Cuatro `.npy` de ejemplo. `tests/fixtures/sample_projections/` está vacía; se generan
  con el ayudante de las pruebas, que ya produce `.npy` válidos de 128 × 128:

  ```bash
  python -c "from pathlib import Path; from tests.fixtures.projection_files import valid_npy; [Path(f'tests/fixtures/sample_projections/angle_{a:03d}.npy').write_bytes(valid_npy(a)) for a in (0, 45, 90, 135)]"
  ```

  Son datos sintéticos de prueba, no radiografías: con los modelos reales no dan un
  resultado clínico.

## 1. Verificaciones sin servicios externos

```bash
ruff check src tests
python scripts/check_naming_convention.py
pytest -m "unit or architecture"
node --test "tests/unit/web/*.js"
coverage run -m pytest -m unit && coverage report --include="src/radvol3d/api/*" --fail-under=80
```

Resultado esperado: todo en verde. `test_layer_boundaries.py` sin cambios y sin fallos
(ningún `persistence`, `psycopg`, `supabase` ni `torch` en `api/`).

## 2. Migración de la tabla `lesion`

En el editor SQL de Supabase (primero en la base de prueba), ejecutar
`docs/database/schema/002_add_lesion_organ.sql`. Comprobar:

```sql
select column_name, is_nullable from information_schema.columns
where table_name = 'lesion' and column_name = 'organ';
```

Resultado esperado: una fila, `organ`, `NO`.

## 3. Integración, punta a punta y concurrencia

```bash
pytest -m integration
pytest -m e2e
pytest -m concurrency
```

Resultado esperado:

- `integration`: cada fila de `lesion` con su `organ` y su propio `mesh_path`; el borrado
  no deja ningún archivo bajo el código del estudio.
- `e2e`: el flujo crear → subir → procesar → estado `completed` → resultado → bajar mallas →
  borrar pasa completo (SC-001).
- `concurrency`: mientras un estudio se procesa, las consultas de estado responden en menos
  de 1 s (SC-003).

## 4. Recorrido manual con el servicio levantado

Con los modelos reales (`uvicorn radvol3d.main:app`), el paso de procesar tarda minutos en
CPU (EN-2). Para un recorrido rápido, levantar la aplicación con las estrategias dobles y la
base de `.env.test`, con la misma fábrica que usa la prueba `e2e`:

```bash
uvicorn --factory tests.e2e.app_with_fakes:create_app_with_fakes
```

1. `POST /studies` con `{"study_code": "qs_001", "organ": "lung"}` → 201, `pending`.
2. `POST /studies/qs_001/projections` con los cuatro campos `angle_000` a `angle_135` →
   201.
3. `POST /studies/qs_001/process` → 202 en menos de 1 s (SC-002).
4. `GET /studies/qs_001/status` hasta `completed`; las etapas avanzan en orden.
5. `GET /studies/qs_001/result` → URLs de `organ.glb`, `tumor.glb`, `volume.npy` y una
   `mesh_url` por lesión.
6. Abrir `http://127.0.0.1:8000/viewer/qs_001`:
   - el órgano se ve semitransparente y cada lesión opaca, en su color;
   - la lista muestra una fila por lesión, con su color, órgano `lung`, ubicación, volumen,
     diámetro y confianza, sin `region_id`;
   - arrastrar rota, la rueda acerca, el botón derecho desplaza y el botón de vista inicial
     vuelve al encuadre del órgano;
   - elegir una fila resalta su malla;
   - las mallas se ven en menos de 5 s (SC-004).
7. Repetir el paso 6 con un estudio `pending` (muestra el estado y se actualiza solo) y con
   un código inexistente (muestra que no existe).
8. `DELETE /studies/qs_001` → 204; `GET /studies/qs_001/status` → 404.

## 5. Casos de error rápidos

| Pedido | Esperado |
|---|---|
| `POST /studies` con el mismo código dos veces | 409 la segunda |
| `POST /studies` con `organ: "liver"` | 503, mensaje sobre el modelo de hígado |
| `POST /studies` con `national_id: "12"` | 422, y el cuerpo no contiene `"12"` |
| subir un PNG en `angle_045` | 422, el mensaje nombra 45 |
| subir un archivo de 2 MiB | 413 |
| `POST /process` sin proyecciones | 409 |
| `GET /result` de un estudio `processing` | 409 con el estado |
| `DELETE` de un estudio `processing` | 409 |
