// Pruebas del visor del modo de una radiografia (radiograph_view.js).
// Corren con el ejecutor de Node, sin npm: node --test "tests/unit/web/*.js"
// Convencion del proyecto: snake_case tambien en JavaScript.

import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ORIENTATION_FACES,
  RELATIVE_LABEL,
  face_view_direction,
  field_of_view_text,
  fit_rect,
  format_length,
  other_warnings,
  parse_npy,
  slice_extent,
  slice_offset_text,
  slice_position_text,
  VALIDATION_IMAGES,
  validation_rows,
} from "../../../src/radvol3d/static/js/radiograph_view.js";

const SHAPE = [128, 128, 128];
// LIDC-IDRI-0002 sin mm: 2007 filas x 1721 columnas -> voxel relativo (R, A, S).
const RELATIVE_VOXEL = [1721 / 128, 1721 / 128, 2007 / 128];

test("el coronal y el sagital conservan la proporcion de la placa", () => {
  const coronal = slice_extent("coronal", SHAPE, RELATIVE_VOXEL);
  const sagittal = slice_extent("sagittal", SHAPE, RELATIVE_VOXEL);

  assert.ok(Math.abs(coronal.height / coronal.width - 2007 / 1721) < 1e-9);
  assert.ok(Math.abs(sagittal.height / sagittal.width - 2007 / 1721) < 1e-9);
});

test("el axial usa los voxeles horizontal y de profundidad", () => {
  const axial = slice_extent("axial", SHAPE, [2, 3, 7]);

  assert.deepEqual(axial, { width: 128 * 2, height: 128 * 3 });
});

test("con voxeles cubicos los cortes son cuadrados, como en el visor de siempre", () => {
  for (const plane of ["axial", "coronal", "sagittal"]) {
    const extent = slice_extent(plane, SHAPE, [2.5, 2.5, 2.5]);
    assert.equal(extent.width, extent.height);
  }
});

test("un plano desconocido falla", () => {
  assert.throws(() => slice_extent("oblicuo", SHAPE, [1, 1, 1]));
});

test("el corte se encaja centrado y sin deformar", () => {
  const rect = fit_rect({ width: 100, height: 200 }, 300, 300);

  assert.deepEqual(rect, { x: 75, y: 0, width: 150, height: 300 });
  assert.equal(rect.height / rect.width, 2);
});

test("las longitudes van en cm o en unidades relativas", () => {
  assert.equal(format_length(423, false), "42,3 cm");
  assert.equal(format_length(1721, true), "1721 u");
  assert.equal(format_length(Number.NaN, false), "—");
});

test("el campo de vision sale en el orden R, A, S", () => {
  assert.equal(field_of_view_text(SHAPE, [3.3047, 3.3047, 3.1339], false), "42,3 cm × 42,3 cm × 40,1 cm");
  assert.equal(field_of_view_text(SHAPE, RELATIVE_VOXEL, true), "1721 u × 1721 u × 2007 u");
});

test("la posicion del corte se mide desde el centro del volumen", () => {
  assert.equal(slice_offset_text(0.5, 128, 3, false), "centro");
  assert.equal(slice_offset_text(1, 128, 2, false), "+12,7 cm");
  assert.equal(slice_offset_text(0, 128, 2, true), "−127 u");
});

test("el rotulo de medidas relativas es el que pide la especificacion", () => {
  assert.equal(RELATIVE_LABEL, "medidas relativas (sin tamaño de píxel)");
});

test("parse_npy lee un .npy float32 en orden C", () => {
  const header = "{'descr': '<f4', 'fortran_order': False, 'shape': (2, 1, 1), }";
  const total = Math.ceil((10 + header.length + 1) / 64) * 64;
  const padded = header + " ".repeat(total - 10 - header.length - 1) + "\n";
  const bytes = new Uint8Array(10 + padded.length + 8);
  bytes.set([0x93, ...Array.from("NUMPY", (c) => c.charCodeAt(0)), 1, 0], 0);
  new DataView(bytes.buffer).setUint16(8, padded.length, true);
  bytes.set(Array.from(padded, (c) => c.charCodeAt(0)), 10);
  new Float32Array(bytes.buffer, 10 + padded.length, 2).set([0.25, 0.75]);

  const npy = parse_npy(bytes.buffer);

  assert.deepEqual(npy.shape, [2, 1, 1]);
  assert.equal(npy.fortran, false);
  assert.deepEqual(Array.from(npy.data), [0.25, 0.75]);
});

test("cada cara del cubo lleva la camara a su lado de la escena", () => {
  assert.deepEqual(face_view_direction(0), [1, 0, 0]); // R
  assert.deepEqual(face_view_direction(1), [-1, 0, 0]); // L
  assert.deepEqual(face_view_direction(4), [0, 0, 1]); // A
  assert.deepEqual(face_view_direction(5), [0, 0, -1]); // P
  const top = face_view_direction(2); // S: desde arriba, con un desvio minimo
  assert.ok(top[1] > 0.999 && top[2] > 0);
  assert.ok(Math.abs(Math.hypot(...top) - 1) < 1e-12);
  assert.equal(face_view_direction(9), null);
});

test("las caras del cubo son las del visor de siempre", () => {
  assert.deepEqual(ORIENTATION_FACES.map((face) => face.label), ["R", "L", "S", "I", "A", "P"]);
});

test("la posicion del corte dice centrado en el medio", () => {
  assert.equal(slice_position_text(50), "centrado");
  assert.equal(slice_position_text("73"), "73 %");
});

test("el aviso de sin tamano de pixel no se repite en la lista de avisos", () => {
  const warnings = [
    "Ventana (VOI LUT) del DICOM descartada: saturaba el 100% de la imagen.",
    "El DICOM no trae tamano de pixel: no se pueden dar medidas en mm.",
    "Sin tamaño de píxel en el DICOM: medidas relativas (sin tamaño de píxel).",
  ];

  assert.deepEqual(other_warnings(warnings, true), [warnings[0]]);
  assert.deepEqual(other_warnings(warnings, false), warnings);
  assert.deepEqual(other_warnings(undefined, true), []);
});

// ---- Validacion frontal (T3) ----

const VALIDATION_MM = {
  ncc: 0.7881,
  medidas_en_mm: true,
  ajuste: {
    escala_horizontal: 1.0093, escala_vertical: 1.0695,
    desplazamiento_horizontal_px: 0.12, desplazamiento_vertical_px: 2.06,
    desplazamiento_horizontal_mm: 0.4, desplazamiento_vertical_mm: 6.5,
  },
  pulmones: {
    disponible: true, dice_2d: 0.7772,
    placa: { ancho_px: 73, alto_px: 62, ancho_mm: 241.2, alto_mm: 194.3 },
    reconstruccion: { ancho_px: 79, alto_px: 61, ancho_mm: 261.1, alto_mm: 191.2 },
  },
};

test("el panel muestra NCC, escala, desplazamiento, Dice y medidas en mm", () => {
  const rows = validation_rows(VALIDATION_MM);
  const by_label = Object.fromEntries(rows.map((row) => [row.label, row]));

  assert.equal(by_label["Similitud (NCC)"].value, "0,788");
  assert.match(by_label["Similitud (NCC)"].explain, /0,72 a 0,82 con el mismo paciente y de 0,42/);
  assert.equal(by_label["Escala de ajuste (H / V)"].value, "1,01 / 1,07");
  assert.match(by_label["Escala de ajuste (H / V)"].explain, /1,10 = la reconstrucción es ~10 % más pequeña/);
  assert.equal(by_label["Desplazamiento (H / V)"].value, "0,1 / 2,1 px");
  assert.match(by_label["Desplazamiento (H / V)"].explain, /En mm: 0,4 \/ 6,5/);
  assert.equal(by_label["Superposición de pulmones (Dice 2D)"].value, "0,777");
  assert.equal(by_label["Pulmones, ancho × alto"].value, "placa 241 × 194 mm");
  assert.equal(by_label["Pulmones, ancho × alto"].explain, "Reconstrucción: 261 × 191 mm.");
});

test("sin mm reales las medidas van en px y el desplazamiento sin mm", () => {
  const values = { ...VALIDATION_MM, medidas_en_mm: false, ajuste: { ...VALIDATION_MM.ajuste } };
  delete values.ajuste.desplazamiento_horizontal_mm;

  const rows = validation_rows(values);

  assert.equal(rows[4].value, "placa 73 × 62 px");
  assert.doesNotMatch(rows[2].explain, /mm/);
});

test("sin los dos pulmones el Dice y las medidas dicen no disponible", () => {
  const rows = validation_rows({ ...VALIDATION_MM, pulmones: { disponible: false } });

  assert.equal(rows[3].value, "no disponible");
  assert.equal(rows[4].value, "no disponible");
  assert.equal(rows[0].value, "0,788");
});

test("no hay semaforos ni aprobado o reprobado", () => {
  const text = JSON.stringify(validation_rows(VALIDATION_MM)).toLowerCase();

  assert.doesNotMatch(text, /aprobad|reprobad|correcto|incorrecto/);
});

test("cada imagen del panel tiene su texto", () => {
  assert.deepEqual(Object.keys(VALIDATION_IMAGES), ["input", "simulated", "overlay"]);
});
