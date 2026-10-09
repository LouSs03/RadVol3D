// Interfaz de carga de proyecciones.
// Convencion del proyecto: snake_case tambien en JavaScript.

const api_base = "";

async function fetch_health() {
  const respuesta = await fetch(`${api_base}/health`);
  return respuesta.json();
}

// TODO: formulario de carga y llamada a la reconstruccion
export { fetch_health };
