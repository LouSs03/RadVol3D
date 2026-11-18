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

// ---------------- Validacion frontal (panel "Radiografia y validacion") ----------------

// Que muestra cada boton del panel y su texto bajo la imagen.
export const VALIDATION_IMAGES = {
  input: "La placa exacta que recibió el modelo, reducida a 128 × 128.",
  simulated: "Radiografía simulada: la TC reconstruida vista de frente (promedio a lo largo de la profundidad).",
  overlay: "La placa con los contornos de los campos pulmonares de la placa y de la reconstrucción.",
};

function decimal(value, digits) {
  return Number(value).toFixed(digits).replace(".", ",");
}

function size_text(size, in_mm) {
  if (!size) return "—";
  return in_mm && size.ancho_mm !== undefined
    ? Math.round(size.ancho_mm) + " × " + Math.round(size.alto_mm) + " mm"
    : size.ancho_px + " × " + size.alto_px + " px";
}

// Las filas del panel: rotulo, valor y una explicacion corta. Sin semaforos ni
// "aprobado/reprobado": no hay umbrales estandar, solo valores y la referencia de T1.
export function validation_rows(values) {
  const fit = values.ajuste || {};
  const lungs = values.pulmones || {};
  const in_mm = Boolean(values.medidas_en_mm);
  const shift = decimal(fit.desplazamiento_horizontal_px, 1) + " / " + decimal(fit.desplazamiento_vertical_px, 1) + " px";
  let shift_explain = "Cuánto habría que mover la reconstrucción (horizontal / vertical) para calzar con la placa.";
  if (in_mm && fit.desplazamiento_horizontal_mm !== undefined) {
    shift_explain += " En mm: " + decimal(fit.desplazamiento_horizontal_mm, 1) + " / " + decimal(fit.desplazamiento_vertical_mm, 1) + ".";
  }
  return [
    {
      label: "Similitud (NCC)",
      value: decimal(values.ncc, 3),
      explain: "Parecido entre la placa y la radiografía simulada (−1 a 1). En la validación con 4 placas reales fue de 0,72 a 0,82 con el mismo paciente y de 0,42 en promedio con otro paciente.",
    },
    {
      label: "Escala de ajuste (H / V)",
      value: decimal(fit.escala_horizontal, 2) + " / " + decimal(fit.escala_vertical, 2),
      explain: "Cuánto habría que agrandar la reconstrucción para calzar con la placa. 1,00 = mismo tamaño; 1,10 = la reconstrucción es ~10 % más pequeña.",
    },
    {
      label: "Desplazamiento (H / V)",
      value: shift,
      explain: shift_explain,
    },
    {
      label: "Superposición de pulmones (Dice 2D)",
      value: lungs.disponible ? decimal(lungs.dice_2d, 3) : "no disponible",
      explain: lungs.disponible
        ? "De 0 a 1: cuánto coinciden los campos pulmonares de la placa y de la reconstrucción."
        : "No se encontraron los dos pulmones en alguna de las dos imágenes.",
    },
    {
      label: "Pulmones, ancho × alto",
      value: lungs.disponible ? "placa " + size_text(lungs.placa, in_mm) : "no disponible",
      explain: lungs.disponible ? "Reconstrucción: " + size_text(lungs.reconstruccion, in_mm) + "." : "",
    },
  ];
}
