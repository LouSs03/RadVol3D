// Logica del historial que no dibuja ni llama a la API (research.md R7 de 005).
// Son funciones puras: las importa index.html y las prueba node --test en
// tests/unit/web/test_history_view.js.
// Convencion del proyecto: snake_case tambien en JavaScript.

// Estudios por pagina; el mismo valor por defecto que GET /studies.
export const HISTORY_PAGE_SIZE = 50;

// Clave del historial que la pagina guardaba antes en localStorage. Solo se usa para
// borrarla: el historial ahora sale de la API (research.md R6 de 005).
export const LEGACY_HISTORY_KEY = "radvol3d.history.v1";

const NO_VALUE = "—";
const number_format = new Intl.NumberFormat("es", { maximumFractionDigits: 1 });

// Volumen en mm3 con el formato del visor: cm3 desde 1 cm3 y mm3 por debajo. El visor y
// el historial usan esta misma funcion para que muestren el mismo numero (SC-003 de 005).
export function format_volume(mm3) {
  return mm3 >= 1000 ? number_format.format(mm3 / 1000) + " cm³" : number_format.format(mm3) + " mm³";
}

function is_completed(entry) {
  return entry.status === "completed";
}

// Numero de lesiones de una fila. Solo un estudio completed tiene resultado.
export function lesion_count_text(entry) {
  if (!is_completed(entry) || typeof entry.lesion_count !== "number") return NO_VALUE;
  return String(entry.lesion_count);
}

// Volumen total de lesion de una fila: la suma de todas sus lesiones (FR-006 de 005).
export function volume_text(entry) {
  const volume = entry.total_lesion_volume_mm3;
  if (!is_completed(entry) || typeof volume !== "number") return NO_VALUE;
  return volume === 0 ? "Sin lesiones" : format_volume(volume);
}

// DNI de una fila: completo, o "sin DNI" si el paciente no lo registro (FR-010 de 005).
export function national_id_text(entry) {
  return entry.national_id || "sin DNI";
}

// Lo que se escribe en el filtro: solo digitos, como maximo ocho.
export function clean_national_id(value) {
  return String(value ?? "").replace(/[^0-9]/g, "").slice(0, 8);
}

export function is_valid_national_id(value) {
  return /^[0-9]{8}$/.test(value);
}
