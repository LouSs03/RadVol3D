# Pruebas de concurrencia

El servicio comparte dos recursos caros entre todas las peticiones: los modelos
cargados en memoria y la conexion a PostgreSQL. Los fallos de ese tipo no
aparecen con un solo usuario. Se marcan con `@pytest.mark.concurrency`.

Necesitan `.env.test` (el Supabase de prueba), no el servicio levantado: llaman a
`StudyService` directamente, con los dobles de las estrategias. Reutilizan las
fixtures y la limpieza de `tests/integration/conftest.py`. Sin `.env.test`, se omiten.

Tres casos que valen la pena:

1. Dos peticiones simultaneas sobre el mismo `study_code` no deben dejar filas
   duplicadas ni un archivo a medio escribir en Storage.
2. Varias reconstrucciones a la vez no deben cargar el modelo una vez por
   peticion: eso agotaria la memoria.
3. Bajo carga, ninguna peticion debe quedarse esperando una conexion que nunca
   se devuelve al grupo.
