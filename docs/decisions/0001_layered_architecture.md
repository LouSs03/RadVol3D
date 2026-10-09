# 0001 - Arquitectura en capas cerradas

**Estado:** aceptada
**Fecha:** TODO

## Contexto

El sistema tiene cuatro responsabilidades bien distintas: interfaz, logica,
persistencia y datos. Cuatro personas trabajan en paralelo sobre el mismo
repositorio.

## Decision

Arquitectura en capas cerradas: cada capa llama solo a la inmediata inferior. Se
agrega un piso de tipos compartidos (`domain`) sin logica ni entrada y salida,
que todas pueden importar.

## Consecuencias

- Cada persona trabaja en su capa sin bloquear a las demas.
- Un cambio en la base de datos no llega hasta el HTML.
- Hace falta una prueba automatica que verifique los limites, porque la
  disciplina sola no basta: `tests/architecture/test_layer_boundaries.py`.
