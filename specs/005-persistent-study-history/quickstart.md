# Quickstart: validar el historial persistente

Guía para comprobar la funcionalidad de punta a punta. Las rutas y las formas de las
respuestas están en [contracts/http_api_history.md](contracts/http_api_history.md); los tipos,
en [data-model.md](data-model.md).

## Requisitos

- Los mismos de [004](../004-rest-api-viewer/quickstart.md#requisitos): `.venv`, Node 22 y
  un Supabase con `001_create_tables.sql` y `002_add_lesion_organ.sql` aplicados.
- No hay migración nueva.

## 1. Verificaciones sin servicios externos

```bash
ruff check src tests
python scripts/check_naming_convention.py
pytest -m "unit or architecture"
node --test "tests/unit/web/*.js"
```

Resultado esperado:

- todo en verde;
- `test_layer_boundaries.py` sin cambios;
- las pruebas nuevas cubren lo siguiente.

| Prueba | Qué verifica |
|---|---|
| Router del historial | Orden. Paginación (`has_more`). `limit` 0 o 101 → 422. Búsqueda con DNI válido. DNI de 7 o 9 dígitos o con letras → 422 sin el valor enviado. Respuesta sin `first_name` ni `last_name` |
| Servicio | `lesion_count` y volumen en `null` fuera de `completed`; `0` y `0.0` en `completed` sin lesiones |
| Repositorio | Filtro por DNI como parámetro. Conversión de `numeric` a `float`. DNI inválido → `InvalidPatientDataError` sin el valor |
| `history_view.js` | `format_volume` (mm³ por debajo de 1000 y cm³ desde 1000). Textos de volumen, DNI y lesiones por estado. Limpieza y validación del DNI |
| Registros | Ningún registro emitido durante `POST /studies/search` contiene el DNI |

## 2. Integración contra la base de prueba

```bash
pytest -m integration -k history
```

La prueba crea tres estudios:

- A, con DNI X y lesiones de volumen conocido;
- B, con DNI X y sin procesar;
- C, sin DNI.

Resultado esperado:

- **Historial completo**: aparecen A, B y C, del más reciente al más antiguo.
- **Estudio A**: el volumen es la suma exacta de sus lesiones.
- **Estudio B**: `lesion_count` y el volumen son `null`.
- **Estudio C**: el DNI es `null`.
- **Búsqueda por X**: devuelve A y B, nada más.

## 3. Prueba manual en el navegador

1. Levantar el servicio: `uvicorn radvol3d.main:app`.
2. Abrir `http://127.0.0.1:8000/static/`, crear un estudio con DNI y procesarlo hasta
   `completed`.
3. Abrir el historial en otro navegador, o en una ventana privada.
   - **Esperado**: el estudio aparece con su DNI completo, su número de lesiones y su
     volumen (SC-001).
4. Abrir ese estudio en el visor.
   - **Esperado**: la suma de los volúmenes de la lista de lesiones coincide con el
     historial, al redondeo mostrado (SC-003).
5. En el historial, escribir el DNI en el filtro.
   - **Esperado**: solo aparecen los estudios de ese paciente.
   - **Esperado**: el hash de la URL sigue siendo `#/history`.
   - **Esperado**: en la terminal de uvicorn, la línea de acceso dice
     `POST /studies/search`, sin el DNI (FR-012).
6. Escribir `1234567`.
   - **Esperado**: un mensaje pide ocho dígitos y no sale ninguna petición (pestaña Red).
7. Borrar un estudio desde otro navegador y recargar el historial.
   - **Esperado**: ya no aparece.
8. Detener el servicio y recargar el historial.
   - **Esperado**: un mensaje de error con "Reintentar" y ninguna fila vieja (FR-014).
9. En las herramientas del navegador, revisar `localStorage`.
   - **Esperado**: no existe `radvol3d.history.v1`, y ninguna clave contiene un DNI.

## 4. Rendimiento (SC-002)

Con la base de prueba poblada con 500 estudios (`scripts/seed_database.py`, si admite esa
cantidad; si no, una prueba de integración que los cree y los borre):

```bash
curl -s -o /dev/null -w "%{time_total}\n" "http://127.0.0.1:8000/studies?limit=50"
```

Esperado: la primera página se dibuja completa en menos de 2 s en el entorno de
demostración. Se anota el valor medido; no se inventa ninguno.
