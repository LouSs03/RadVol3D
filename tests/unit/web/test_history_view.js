// Pruebas de la logica del historial que no dibuja (research.md R7 de 005).
// Corren con el ejecutor de Node, sin npm: node --test "tests/unit/web/*.js"
// Convencion del proyecto: snake_case tambien en JavaScript.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  HISTORY_PAGE_SIZE,
  LEGACY_HISTORY_KEY,
  clean_national_id,
  format_volume,
  is_valid_national_id,
  lesion_count_text,
  national_id_text,
  volume_text,
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

test("format_volume usa mm3 por debajo de 1 cm3 y cm3 desde ahi, como el visor", () => {
  assert.equal(format_volume(15.6), "15,6 mm³");
  assert.equal(format_volume(999), "999 mm³");
  assert.equal(format_volume(1000), "1 cm³");
  assert.equal(format_volume(1843.75), "1,8 cm³");
});

test("un estudio completed sin lesiones dice que no las tiene", () => {
  assert.equal(
    volume_text({ status: "completed", lesion_count: 0, total_lesion_volume_mm3: 0 }),
    "Sin lesiones",
  );
});

test("un estudio completed con lesiones muestra su volumen total", () => {
  assert.equal(
    volume_text({ status: "completed", lesion_count: 2, total_lesion_volume_mm3: 1843.75 }),
    "1,8 cm³",
  );
});

test("un estudio sin terminar no muestra volumen", () => {
  for (const status of ["pending", "processing", "failed"]) {
    assert.equal(volume_text({ status, lesion_count: null, total_lesion_volume_mm3: null }), "—");
  }
});

test("el DNI se muestra completo, o sin DNI si no lo tiene", () => {
  assert.equal(national_id_text({ national_id: "12345678" }), "12345678");
  assert.equal(national_id_text({ national_id: null }), "sin DNI");
});

test("clean_national_id deja solo digitos, como maximo ocho", () => {
  assert.equal(clean_national_id(" 12a34-5678 "), "12345678");
  assert.equal(clean_national_id("1234567890"), "12345678");
  assert.equal(clean_national_id(null), "");
});

test("is_valid_national_id exige exactamente ocho digitos", () => {
  assert.equal(is_valid_national_id("12345678"), true);
  for (const value of ["1234567", "", "1234567a", "123456789"]) {
    assert.equal(is_valid_national_id(value), false);
  }
});
