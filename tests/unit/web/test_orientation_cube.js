// Pruebas del cubo de orientacion de los visores 3D (orientation_cube.js).
// Corren con el ejecutor de Node, sin npm: node --test "tests/unit/web/*.js"
// Convencion del proyecto: snake_case tambien en JavaScript.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  DRAG_RADIANS_PER_PIXEL,
  ORIENTATION_FACES,
  face_view_direction,
  orbit_after_drag,
} from "../../../src/radvol3d/static/js/orientation_cube.js";

const close = (a, b, eps = 1e-9) => a.every((value, i) => Math.abs(value - b[i]) < eps);

test("las caras son R, L, S, I, A, P en el orden de BoxGeometry", () => {
  assert.deepEqual(ORIENTATION_FACES.map((face) => face.label), ["R", "L", "S", "I", "A", "P"]);
});

test("cada cara lleva la camara a su lado de la escena", () => {
  assert.deepEqual(face_view_direction(0), [1, 0, 0]);
  assert.deepEqual(face_view_direction(1), [-1, 0, 0]);
  assert.deepEqual(face_view_direction(4), [0, 0, 1]);
  assert.deepEqual(face_view_direction(5), [0, 0, -1]);
  const below = face_view_direction(3);
  assert.ok(below[1] < -0.999 && below[2] > 0);
  assert.equal(face_view_direction(6), null);
});

test("arrastrar media vuelta en horizontal lleva la camara al otro lado", () => {
  const pixels = Math.PI / DRAG_RADIANS_PER_PIXEL;

  const after = orbit_after_drag([0, 0, 10], pixels, 0);

  assert.ok(close(after, [0, 0, -10], 1e-6));
});

test("arrastrar a la derecha gira como la vista principal (la camara va a la izquierda)", () => {
  const after = orbit_after_drag([0, 0, 10], 10, 0);

  assert.ok(after[0] < 0);
});

test("el arrastre conserva la distancia al centro", () => {
  const after = orbit_after_drag([3, 4, 5], 37, -12);

  assert.ok(Math.abs(Math.hypot(...after) - Math.hypot(3, 4, 5)) < 1e-9);
});

test("arrastrar en vertical no pasa por encima del polo", () => {
  const after = orbit_after_drag([0, 0, 10], 0, 10_000);

  assert.ok(after[1] > 9.99);
  assert.ok(after[2] > 0);
});

test("sin distancia no hay giro", () => {
  assert.deepEqual(orbit_after_drag([0, 0, 0], 50, 50), [0, 0, 0]);
});
