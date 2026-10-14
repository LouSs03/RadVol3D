// Orientacion del volumen y de las mallas en el visor (docs/models/meshing.md).
// Son datos y funciones puras: las importa index.html y las prueba node --test en
// tests/unit/web/test_volume_orientation.js.
// Convencion del proyecto: snake_case tambien en JavaScript.
//
// El volumen y las mallas llegan con los ejes del volumen de TA-2, armado desde el
// mundo RAS+ del NIfTI (el cuaderno que genera los casos lo fija y lo comprueba):
//   eje 0 -> derecha del paciente (R)
//   eje 1 -> adelante (A, anterior)
//   eje 2 -> cabeza (S, superior)

// Hacia donde apunta cada eje del volumen en la escena de three.js, que tiene Y hacia
// arriba y Z hacia la camara inicial: la cabeza arriba y el frente del paciente hacia
// la camara. Como en toda vista de frente, la derecha del paciente queda a la izquierda
// de la pantalla. Es una rotacion pura (sin espejo): ningun organo se invierte.
export const VOLUME_AXES_IN_SCENE = [
  [1, 0, 0],
  [0, 0, -1],
  [0, 1, 0],
];

// La camara empieza de frente al paciente.
export const HOME_DIRECTION = [0, 0, 1];

// Como se dibuja cada corte, con la convencion de radiologia:
// - axial: visto desde los pies, adelante arriba y la derecha del paciente a la izquierda;
// - coronal: de frente, la cabeza arriba y la derecha del paciente a la izquierda;
// - sagital: de lado, la cabeza arriba y adelante a la izquierda.
// fraction (0 a 1) elige la posicion del corte sobre su eje. Devuelve el tamano de la
// imagen, el indice plano (orden C) del voxel de cada fila y columna, y los rotulos de
// los cuatro bordes.
export function slice_layout(plane, shape, fraction) {
  const [a, b, c] = shape;
  const at = (n) => Math.round(Math.min(1, Math.max(0, fraction)) * (n - 1));
  const flat = (i, j, k) => (i * b + j) * c + k;
  if (plane === "axial") {
    const k = at(c);
    return {
      rows: b,
      cols: a,
      index_of: (row, col) => flat(a - 1 - col, b - 1 - row, k),
      labels: { top: "Ant", bottom: "Pos", left: "Der", right: "Izq" },
    };
  }
  if (plane === "coronal") {
    const j = at(b);
    return {
      rows: c,
      cols: a,
      index_of: (row, col) => flat(a - 1 - col, j, c - 1 - row),
      labels: { top: "Sup", bottom: "Inf", left: "Der", right: "Izq" },
    };
  }
  if (plane === "sagittal") {
    const i = at(a);
    return {
      rows: c,
      cols: b,
      index_of: (row, col) => flat(i, b - 1 - col, c - 1 - row),
      labels: { top: "Sup", bottom: "Inf", left: "Ant", right: "Pos" },
    };
  }
  throw new Error("Plano desconocido: " + plane);
}
