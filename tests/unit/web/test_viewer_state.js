// Pruebas de la logica del visor que no dibuja (research.md R13 y R14).
// Corren con el ejecutor de Node, sin npm: node --test tests/unit/web/
// Convencion del proyecto: snake_case tambien en JavaScript.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  LESION_PALETTE,
  ORGAN_COLOR,
  ORGAN_OPACITY,
  REFRESH_MS,
  lesion_color,
  lesion_rows,
  status_view,
  study_code_from_path,
} from "../../../src/radvol3d/web/js/viewer_state.js";

const OKABE_ITO_WITHOUT_BLACK = [
  "#E69F00",
  "#56B4E9",
  "#009E73",
  "#F0E442",
  "#0072B2",
  "#D55E00",
  "#CC79A7",
];

function result_with(lesions) {
  return {
    study_code: "lung_028",
    organ_mesh_url: "/studies/lung_028/result/organ.glb",
    tumor_mesh_url: "/studies/lung_028/result/tumor.glb",
    volume_url: "/studies/lung_028/result/volume.npy",
    lesions,
  };
}

function lesion(number, overrides = {}) {
  return {
    lesion_number: number,
    organ: "lung",
    location: `posicion ${number}`,
    volume_mm3: 8000,
    max_diameter_mm: 34.64,
    confidence: 0.9,
    mesh_url: `/studies/lung_028/result/lesions/${number}.glb`,
    ...overrides,
  };
}

function stages(...statuses) {
  const names = ["preprocessing", "reconstruction", "segmentation", "meshing"];
  return statuses.map((status, index) => ({
    stage_number: index + 1,
    stage_name: names[index],
    status,
  }));
}

test("la paleta es la de Okabe-Ito sin el negro", () => {
  assert.deepEqual(LESION_PALETTE, OKABE_ITO_WITHOUT_BLACK);
});

test("el organo es gris claro, semitransparente y distinto de la paleta", () => {
  assert.match(ORGAN_COLOR, /^#[0-9A-F]{6}$/);
  assert.ok(!LESION_PALETTE.includes(ORGAN_COLOR));
  assert.equal(ORGAN_OPACITY, 0.3);
});

test("cada lesion toma un color y la paleta se repite desde la octava", () => {
  assert.equal(lesion_color(0), "#E69F00");
  assert.equal(lesion_color(6), "#CC79A7");
  assert.equal(lesion_color(7), "#E69F00");
  assert.equal(lesion_color(15), "#56B4E9");
});

test("hay una fila por lesion, con su color y sin region_id", () => {
  const rows = lesion_rows(result_with([lesion(1, { region_id: 1 }), lesion(2)]));

  assert.equal(rows.length, 2);
  assert.deepEqual(rows[0], {
    lesion_number: 1,
    color: "#E69F00",
    organ: "lung",
    location: "posicion 1",
    volume_mm3: 8000,
    max_diameter_mm: 34.64,
    confidence: 0.9,
    mesh_url: "/studies/lung_028/result/lesions/1.glb",
  });
  assert.equal(rows[1].color, "#56B4E9");
  for (const row of rows) {
    assert.ok(!("region_id" in row));
  }
});

test("una lesion sin diametro muestra una raya", () => {
  const [row] = lesion_rows(result_with([lesion(1, { max_diameter_mm: null })]));

  assert.equal(row.max_diameter_mm, "—");
});

test("un resultado sin lesiones no tiene filas", () => {
  assert.deepEqual(lesion_rows(result_with([])), []);
});

test("pending y processing se vuelven a consultar cada 5 s", () => {
  assert.equal(REFRESH_MS, 5000);
  for (const status of ["pending", "processing"]) {
    const view = status_view(200, { status, stages: stages("waiting", "waiting", "waiting", "waiting") });
    assert.equal(view.action, "refresh");
    assert.equal(view.refresh_ms, 5000);
    assert.match(view.message, new RegExp(status));
  }
});

test("completed carga las mallas", () => {
  const view = status_view(200, { status: "completed", stages: stages("completed", "completed", "completed", "completed") });

  assert.equal(view.action, "load");
});

test("failed muestra la etapa que fallo", () => {
  const view = status_view(200, { status: "failed", stages: stages("completed", "completed", "failed", "skipped") });

  assert.equal(view.action, "show_failure");
  assert.match(view.message, /etapa 3/);
  assert.match(view.message, /segmentation/);
});

test("un estudio que no existe lo dice", () => {
  const view = status_view(404, null);

  assert.equal(view.action, "not_found");
  assert.match(view.message, /no existe/);
});

test("otro error del servidor se muestra sin reintentar", () => {
  const view = status_view(500, { detail: "Error interno del servidor." });

  assert.equal(view.action, "error");
});

test("el codigo del estudio sale de la ruta del visor", () => {
  assert.equal(study_code_from_path("/viewer/lung_028"), "lung_028");
  assert.equal(study_code_from_path("/viewer/lung_028/"), "lung_028");
  assert.equal(study_code_from_path("/viewer/con%20espacio"), "con espacio");
  assert.equal(study_code_from_path("/otra/cosa"), null);
});
