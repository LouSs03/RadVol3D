// Pruebas de la orientacion del volumen en el visor (volume_orientation.js).
// Corren con el ejecutor de Node, sin npm: node --test "tests/unit/web/*.js"
// Convencion del proyecto: snake_case tambien en JavaScript.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  HOME_DIRECTION,
  VOLUME_AXES_IN_SCENE,
  slice_layout,
} from "../../../src/radvol3d/static/js/volume_orientation.js";

const [RIGHT, ANTERIOR, HEAD] = VOLUME_AXES_IN_SCENE;
const SHAPE = [3, 4, 5]; // ejes 0 (R), 1 (A), 2 (S) con tamanos distintos

function dot(u, v) {
  return u[0] * v[0] + u[1] * v[1] + u[2] * v[2];
}

// Producto vectorial; "+ 0" convierte -0 en 0 para comparar con deepEqual.
function cross(u, v) {
  return [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]].map(
    (value) => value + 0,
  );
}

// Coordenadas (i, j, k) del voxel de un indice plano en orden C.
function voxel_of(index) {
  const [, b, c] = SHAPE;
  return [Math.floor(index / (b * c)), Math.floor(index / c) % b, index % c];
}

test("la cabeza va arriba y el frente del paciente hacia la camara", () => {
  assert.deepEqual(HEAD, [0, 1, 0]);
  assert.deepEqual(ANTERIOR, [0, 0, -1]);
});

test("de frente, la derecha del paciente queda orientada consistentemente", () => {
  assert.deepEqual(RIGHT, [1, 0, 0]);
});

test("el giro es una rotacion pura: no refleja el organo", () => {
  for (const u of VOLUME_AXES_IN_SCENE) assert.equal(dot(u, u), 1);
  assert.equal(dot(RIGHT, ANTERIOR), 0);
  assert.equal(dot(RIGHT, HEAD), 0);
  assert.equal(dot(ANTERIOR, HEAD), 0);
  // Determinante +1: R x A = S, como en el sistema RAS+ de origen.
  assert.deepEqual(cross(RIGHT, ANTERIOR), HEAD);
});

test("axial: adelante arriba y la derecha del paciente a la izquierda", () => {
  const layout = slice_layout("axial", SHAPE, 0.5);

  assert.equal(layout.rows, 4);
  assert.equal(layout.cols, 3);
  assert.deepEqual(voxel_of(layout.index_of(0, 0)), [2, 3, 2]);
  assert.deepEqual(voxel_of(layout.index_of(3, 2)), [0, 0, 2]);
  assert.deepEqual(layout.labels, { top: "Ant", bottom: "Pos", left: "Der", right: "Izq" });
});

test("coronal: la cabeza arriba y la derecha del paciente a la izquierda", () => {
  const layout = slice_layout("coronal", SHAPE, 0);

  assert.equal(layout.rows, 5);
  assert.equal(layout.cols, 3);
  assert.deepEqual(voxel_of(layout.index_of(0, 0)), [2, 0, 4]);
  assert.deepEqual(voxel_of(layout.index_of(4, 2)), [0, 0, 0]);
  assert.deepEqual(layout.labels, { top: "Sup", bottom: "Inf", left: "Der", right: "Izq" });
});

test("sagital: la cabeza arriba y adelante a la izquierda", () => {
  const layout = slice_layout("sagittal", SHAPE, 1);

  assert.equal(layout.rows, 5);
  assert.equal(layout.cols, 4);
  assert.deepEqual(voxel_of(layout.index_of(0, 0)), [2, 3, 4]);
  assert.deepEqual(voxel_of(layout.index_of(4, 3)), [2, 0, 0]);
  assert.deepEqual(layout.labels, { top: "Sup", bottom: "Inf", left: "Ant", right: "Pos" });
});

test("cada corte recorre todo su plano, cada voxel una sola vez", () => {
  const fixed_axis = { axial: 2, coronal: 1, sagittal: 0 };
  for (const [plane, axis] of Object.entries(fixed_axis)) {
    const { rows, cols, index_of } = slice_layout(plane, SHAPE, 0.5);
    const seen = new Set();
    for (let row = 0; row < rows; row++) {
      for (let col = 0; col < cols; col++) seen.add(index_of(row, col));
    }
    assert.equal(seen.size, rows * cols);
    const fixed = new Set([...seen].map((index) => voxel_of(index)[axis]));
    assert.equal(fixed.size, 1, plane);
  }
});

test("la posicion del corte se limita al volumen", () => {
  const last = slice_layout("axial", SHAPE, 1.5);
  const first = slice_layout("axial", SHAPE, -0.2);

  assert.equal(voxel_of(last.index_of(0, 0))[2], 4);
  assert.equal(voxel_of(first.index_of(0, 0))[2], 0);
});

test("un plano desconocido se rechaza", () => {
  assert.throws(() => slice_layout("oblicuo", SHAPE, 0.5), /Plano desconocido/);
});
