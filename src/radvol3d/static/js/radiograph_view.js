// Visor del modo de una radiografia (radiograph_viewer.html): datos y funciones puras.
// Las prueba node --test en tests/unit/web/test_radiograph_view.js.
// Convencion del proyecto: snake_case tambien en JavaScript.
//
// Es un visor separado del de cuatro proyecciones (index.html), que no cambia. La
// diferencia principal: aqui el voxel no es cubico ni fijo. X2CT-GAN reconstruye cada
// placa con su propio tamano de pixel, distinto en horizontal y en vertical, y el
// volumen llega con su voxel en los ejes del sistema (R, A, S). Los cortes y la escala
// se dibujan con ese voxel para que nada se vea estirado.
//
// La orientacion de los cortes es la misma del visor de siempre (volume_orientation.js,
// convencion de radiologia): se reutiliza sin cambios.

import { slice_layout } from "./volume_orientation.js";

export const RELATIVE_LABEL = "medidas relativas (sin tamaño de píxel)";

// Que eje del volumen va en las columnas y cual en las filas de cada corte, segun
// slice_layout: axial = columnas R, filas A; coronal = columnas R, filas S;
// sagital = columnas A, filas S.
const SLICE_AXES = {
  axial: { column: 0, row: 1 },
  coronal: { column: 0, row: 2 },
  sagittal: { column: 1, row: 2 },
};

// Ancho y alto reales de un corte (en mm, o en unidades relativas), con el voxel de
// cada eje. Con esto se dibuja sin deformar.
export function slice_extent(plane, shape, voxel_mm) {
  const axes = SLICE_AXES[plane];
  if (!axes) throw new Error("Plano desconocido: " + plane);
  const { rows, cols } = slice_layout(plane, shape, 0.5);
  return { width: cols * voxel_mm[axes.column], height: rows * voxel_mm[axes.row] };
}

// El rectangulo (x, y, ancho, alto) donde dibujar un corte de esa extension dentro de
// un lienzo, centrado y sin deformar.
export function fit_rect(extent, canvas_width, canvas_height) {
  const scale = Math.min(canvas_width / extent.width, canvas_height / extent.height);
  const width = extent.width * scale;
  const height = extent.height * scale;
  return { x: (canvas_width - width) / 2, y: (canvas_height - height) / 2, width, height };
}

// Una longitud para mostrar: en cm si hay mm reales; si no, en unidades relativas.
export function format_length(value_mm, relative) {
  if (!Number.isFinite(value_mm)) return "—";
  if (relative) return Math.round(value_mm) + " u";
  return (value_mm / 10).toFixed(1).replace(".", ",") + " cm";
}

// El campo de vision del volumen (ancho x profundidad x alto), en el orden R, A, S.
export function field_of_view_text(shape, voxel_mm, relative) {
  const parts = shape.map((count, axis) => format_length(count * voxel_mm[axis], relative));
  return parts.join(" × ");
}

// Distancia del corte al centro del volumen sobre un eje, para el rotulo de cada corte.
export function slice_offset_text(fraction, count, voxel, relative) {
  const index = Math.round(Math.min(1, Math.max(0, fraction)) * (count - 1));
  const offset = (index - (count - 1) / 2) * voxel;
  // Con un numero par de cortes el mas cercano al centro queda a medio voxel.
  if (Math.abs(offset) <= voxel / 2 + 1e-9) return "centro";
  return (offset > 0 ? "+" : "−") + format_length(Math.abs(offset), relative);
}

// Eje que recorre cada corte: axial = S, coronal = A, sagital = R.
export const SLICE_NORMAL_AXIS = { axial: 2, coronal: 1, sagittal: 0 };

// Cubo de orientacion: el mismo de los dos visores (orientation_cube.js).
export { ORIENTATION_FACES, face_view_direction } from "./orientation_cube.js";

// Rotulo de la posicion del corte: "centrado" en el medio; si no, el porcentaje.
export function slice_position_text(percent) {
  return Number(percent) === 50 ? "centrado" : Math.round(Number(percent)) + " %";
}

// Los avisos que se listan aparte del de medidas relativas, para no repetirlo: el del
// sistema y los de X2CT que dicen lo mismo con otras palabras.
const NO_PIXEL_PREFIXES = ["El DICOM no trae tamano de pixel", "Entrada en formato imagen: no trae tamano de pixel"];

export function other_warnings(warnings, relative) {
  return (warnings || []).filter((text) => !(relative && (
    text.includes(RELATIVE_LABEL) || NO_PIXEL_PREFIXES.some((prefix) => text.startsWith(prefix))
  )));
}

// Lectura de un .npy (la misma de index.html, copiada para no tocar el visor de siempre).
const NPY_TYPES = {
  f4: Float32Array, f8: Float64Array, i1: Int8Array, u1: Uint8Array, b1: Uint8Array,
  i2: Int16Array, u2: Uint16Array, i4: Int32Array, u4: Uint32Array,
};

export function parse_npy(buffer) {
  const bytes = new Uint8Array(buffer);
  if (bytes.length < 12 || bytes[0] !== 0x93 || String.fromCharCode(...bytes.subarray(1, 6)) !== "NUMPY") return null;
  const view = new DataView(buffer);
  const header_start = bytes[6] === 1 ? 10 : 12;
  const header_length = bytes[6] === 1 ? view.getUint16(8, true) : view.getUint32(8, true);
  const header = new TextDecoder("latin1").decode(bytes.subarray(header_start, header_start + header_length));
  const descr = /'descr'\s*:\s*'([<>|=])([a-z])(\d+)'/.exec(header);
  const shape_match = /'shape'\s*:\s*\(([^)]*)\)/.exec(header);
  if (!descr || !shape_match || descr[1] === ">") return null;
  const array_type = NPY_TYPES[descr[2] + descr[3]];
  if (!array_type) return null;
  const shape = shape_match[1].split(",").map((s) => s.trim()).filter(Boolean).map(Number);
  const count = shape.reduce((a, b) => a * b, 1);
  const start = header_start + header_length;
  const end = start + count * array_type.BYTES_PER_ELEMENT;
  if (buffer.byteLength < end) return null;
  return {
    shape,
    fortran: /'fortran_order'\s*:\s*True/.test(header),
    data: new array_type(buffer.slice(start, end)),
  };
}
