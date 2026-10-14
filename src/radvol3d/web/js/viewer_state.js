// Logica del visor que no dibuja: colores, filas de la lista y que hacer en cada estado.
// Sin DOM ni Three.js, para poder probarla con node --test (research.md R13 y R14).
// Convencion del proyecto: snake_case tambien en JavaScript.

// Paleta de Okabe-Ito sin el negro: siete colores que se distinguen tambien con
// daltonismo. Desde la octava lesion se repite.
export const LESION_PALETTE = [
  "#E69F00",
  "#56B4E9",
  "#009E73",
  "#F0E442",
  "#0072B2",
  "#D55E00",
  "#CC79A7",
];

// El organo va en gris claro y semitransparente, para que las lesiones se vean a traves.
export const ORGAN_COLOR = "#D0D0D0";
export const ORGAN_OPACITY = 0.3;

// Cada cuanto se vuelve a pedir el estado de un estudio que todavia no termino.
export const REFRESH_MS = 5000;

const STAGE_LABELS = {
  preprocessing: "preprocesamiento",
  reconstruction: "reconstruccion",
  segmentation: "segmentacion",
  meshing: "mallas",
};

export function lesion_color(index) {
  return LESION_PALETTE[index % LESION_PALETTE.length];
}

// Una fila por lesion, con el color de su malla. Solo los campos que muestra la
// lista: nunca region_id ni ningun identificador interno.
export function lesion_rows(result) {
  return result.lesions.map((lesion, index) => ({
    lesion_number: lesion.lesion_number,
    color: lesion_color(index),
    organ: lesion.organ,
    location: lesion.location,
    volume_mm3: lesion.volume_mm3,
    max_diameter_mm: lesion.max_diameter_mm ?? "—",
    confidence: lesion.confidence,
    mesh_url: lesion.mesh_url,
  }));
}

// Que mostrar y que hacer segun la respuesta de GET /studies/{code}/status.
export function status_view(http_status, body) {
  if (http_status === 404) {
    return { action: "not_found", message: "El estudio no existe." };
  }
  if (http_status !== 200 || body === null) {
    return {
      action: "error",
      message: body?.detail ?? "No se pudo consultar el estado del estudio.",
    };
  }
  if (body.status === "pending" || body.status === "processing") {
    return {
      action: "refresh",
      refresh_ms: REFRESH_MS,
      message: `El estudio esta en ${body.status}. Esta pagina se actualiza sola.`,
    };
  }
  if (body.status === "failed") {
    const failed = (body.stages ?? []).find((stage) => stage.status === "failed");
    const detail = failed
      ? ` en la etapa ${failed.stage_number} (${failed.stage_name}, ` +
        `${STAGE_LABELS[failed.stage_name] ?? failed.stage_name})`
      : "";
    return { action: "show_failure", message: `El procesamiento fallo${detail}.` };
  }
  return { action: "load", message: "" };
}

// El codigo del estudio es el ultimo tramo de /viewer/<codigo>.
export function study_code_from_path(pathname) {
  const match = /^\/viewer\/([^/]+)\/?$/.exec(pathname);
  return match ? decodeURIComponent(match[1]) : null;
}

// Escala continua de confianza en [0, 1] (HU-3.2):
// 0.00 -> Azul, 0.25 -> Cian, 0.50 -> Verde, 0.75 -> Amarillo, 1.00 -> Rojo.
export const CONFIDENCE_LEGEND_TICKS = ["0.00", "0.25", "0.50", "0.75", "1.00"];

export function confidence_color_hex(value) {
  const v = Math.max(0, Math.min(1, Number(value) || 0));
  let r = 0, g = 0, b = 0;
  if (v < 0.25) {
    const t = v / 0.25;
    r = 0;
    g = Math.round(t * 255);
    b = 255;
  } else if (v < 0.5) {
    const t = (v - 0.25) / 0.25;
    r = 0;
    g = 255;
    b = Math.round((1 - t) * 255);
  } else if (v < 0.75) {
    const t = (v - 0.5) / 0.25;
    r = Math.round(t * 255);
    g = 255;
    b = 0;
  } else {
    const t = (v - 0.75) / 0.25;
    r = 255;
    g = Math.round((1 - t) * 255);
    b = 0;
  }
  return `#${[r, g, b].map((x) => x.toString(16).padStart(2, "0")).join("")}`.toUpperCase();
}
