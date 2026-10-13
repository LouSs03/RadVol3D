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

// Numero de lesiones de una fila. Solo un estudio completed tiene resultado.
export function lesion_count_text(entry) {
  if (entry.status !== "completed" || typeof entry.lesion_count !== "number") return NO_VALUE;
  return String(entry.lesion_count);
}
