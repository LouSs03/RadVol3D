# Pruebas de integracion

Dos capas reales trabajando juntas. Necesitan un Supabase de prueba, nunca el de
produccion. Se marcan con `@pytest.mark.integration`.

Ejemplo de lo que va aqui: guardar un estudio con la capa 3 y volver a leerlo
debe devolver exactamente el mismo diccionario, con las mismas claves y tipos.
