// Pruebas de la logica del historial que no dibuja (research.md R7 de 005).
// Corren con el ejecutor de Node, sin npm: node --test "tests/unit/web/*.js"
// Convencion del proyecto: snake_case tambien en JavaScript.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  HISTORY_PAGE_SIZE,
  LEGACY_HISTORY_KEY,
  lesion_count_text,
} from "../../../src/radvol3d/static/js/history_view.js";

test("las constantes del historial", () => {
  assert.equal(HISTORY_PAGE_SIZE, 50);
  assert.equal(LEGACY_HISTORY_KEY, "radvol3d.history.v1");
});

test("un estudio completed muestra su numero de lesiones", () => {
  assert.equal(lesion_count_text({ status: "completed", lesion_count: 2 }), "2");
  assert.equal(lesion_count_text({ status: "completed", lesion_count: 0 }), "0");
});

test("un estudio sin terminar no muestra lesiones", () => {
  for (const status of ["pending", "processing", "failed"]) {
    assert.equal(lesion_count_text({ status, lesion_count: null }), "—");
  }
});
