# Pruebas de punta a punta (caja negra)

Entran por HTTP y comprueban el resultado sin conocer nada de lo que pasa por
dentro. Son las pruebas de caja negra del proyecto. Se marcan con
`@pytest.mark.e2e` y necesitan el servicio levantado.

Ejemplo: subir cuatro imagenes y recibir el volumen reconstruido junto con el
identificador del estudio.
