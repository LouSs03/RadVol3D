# 0002 - Patron Strategy para reconstruccion y segmentacion

**Estado:** aceptada
**Fecha:** TODO

## Contexto

Hay dos algoritmos de reconstruccion (retroproyeccion simple y modelo EN-1) y un
modelo de segmentacion por organo. La tabla `model` ya guarda `model_name` y
`version` por estudio.

Ademas, la brecha 1 del estado del arte senala que ningun modelo publicado opera
sobre mas de una region anatomica, y que hay que reescribir el sistema entero
para cada organo nuevo.

## Decision

Patron Strategy. Una interfaz por etapa, una implementacion por algoritmo, y una
tuberia que recibe sus estrategias sin saber cuales le tocaron. La eleccion por
organo se concentra en un Factory Method.

## Consecuencias

- Agregar un tercer organo es agregar un archivo, no tocar la tuberia.
- La tuberia se prueba con dobles, sin GPU ni archivo de pesos. Esto es lo que
  hace cumplible la regla de una prueba unitaria por funcionalidad.
- Hay mas archivos y una capa de indireccion. Es el costo que se paga.

## Alternativa descartada

Condicionales por organo dentro de la tuberia. Mas corto al principio, pero cada
organo nuevo obliga a tocar la tuberia, el servicio y la generacion de mallas, y
a acordarse de los tres.
