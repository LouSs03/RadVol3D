// Cubo de orientacion anatomica de los visores 3D (index.html y radiograph_viewer.html).
// Las partes puras las prueba node --test en tests/unit/web/test_orientation_cube.js.
// Convencion del proyecto: snake_case tambien en JavaScript.
//
// El cubo muestra hacia donde mira la camara y ademas sirve para girar la reconstruccion:
// - clic (o toque) en una cara: la camara va a ese lado del organo (vista estandar);
// - arrastrar sobre el cubo: la reconstruccion gira, como al arrastrarla a ella.
// Al usarlo se apaga la rotacion automatica, para que la vista elegida quede quieta.
//
// No importa three: lo recibe quien lo usa (asi las pruebas corren sin el CDN).

// Caras en el orden de los materiales de BoxGeometry (+X, -X, +Y, -Y, +Z, -Z de la escena).
export const ORIENTATION_FACES = [
  { label: "R", color: "#0072B2" },
  { label: "L", color: "#56B4E9" },
  { label: "S", color: "#009E73" },
  { label: "I", color: "#D55E00" },
  { label: "A", color: "#E69F00" },
  { label: "P", color: "#CC79A7" },
];

// Hacia donde va la camara al pulsar cada cara. Arriba y abajo llevan un desvio minimo
// hacia la camara inicial: mirar justo desde el polo deja la orbita sin direccion "arriba".
const FACE_DIRECTIONS = [
  [1, 0, 0], [-1, 0, 0], [0, 1, 0.001], [0, -1, 0.001], [0, 0, 1], [0, 0, -1],
];

export function face_view_direction(material_index) {
  const direction = FACE_DIRECTIONS[material_index];
  if (!direction) return null;
  const length = Math.hypot(...direction);
  return direction.map((value) => value / length);
}

// Radianes por pixel de arrastre sobre el cubo (el cubo mide 90 px: media vuelta ~ 90 px).
export const DRAG_RADIANS_PER_PIXEL = Math.PI / 90;
// Menos que esto, en pixeles, es un clic y no un arrastre.
export const CLICK_TOLERANCE_PX = 4;
const POLE_MARGIN = 1e-3;

// La posicion de la camara respecto del centro despues de arrastrar dx, dy pixeles: el
// mismo sentido que al arrastrar la vista principal (OrbitControls), sin pasar los polos.
export function orbit_after_drag(offset, dx, dy, radians_per_pixel = DRAG_RADIANS_PER_PIXEL) {
  const [x, y, z] = offset;
  const radius = Math.hypot(x, y, z);
  if (!radius) return [x, y, z];
  const theta = Math.atan2(x, z) - dx * radians_per_pixel;
  const phi = Math.min(
    Math.PI - POLE_MARGIN,
    Math.max(POLE_MARGIN, Math.acos(Math.max(-1, Math.min(1, y / radius))) - dy * radians_per_pixel),
  );
  return [
    radius * Math.sin(phi) * Math.sin(theta),
    radius * Math.cos(phi),
    radius * Math.sin(phi) * Math.cos(theta),
  ];
}

// Conecta el cubo con la camara principal. orientation trae { renderer, camera, cube } (el
// renderer y la camara propios del cubo). on_use se llama al tocarlo (apagar el giro).
export function enable_orientation_cube(three, orientation, camera, controls, on_use) {
  const element = orientation.renderer.domElement;
  element.style.touchAction = "none";
  const raycaster = new three.Raycaster();
  let start = null;
  let last = null;
  let dragging = false;

  // Mueve la camara sin la inercia de la orbita: el primer update consume el giro que
  // traia (de un arrastre o de la rotacion automatica) y el segundo deja la posicion.
  const place_camera = (offset) => {
    controls.enableDamping = false;
    controls.update();
    camera.position.copy(controls.target).add(new three.Vector3(...offset));
    controls.update();
    controls.enableDamping = true;
  };
  const current_offset = () => {
    const offset = new three.Vector3().subVectors(camera.position, controls.target);
    return [offset.x, offset.y, offset.z];
  };

  element.addEventListener("pointerdown", (event) => {
    start = last = { x: event.clientX, y: event.clientY };
    dragging = false;
    element.setPointerCapture(event.pointerId);
    on_use();
  });
  element.addEventListener("pointermove", (event) => {
    if (!start) return;
    const moved = Math.hypot(event.clientX - start.x, event.clientY - start.y);
    if (!dragging && moved < CLICK_TOLERANCE_PX) return;
    dragging = true;
    place_camera(orbit_after_drag(current_offset(), event.clientX - last.x, event.clientY - last.y));
    last = { x: event.clientX, y: event.clientY };
  });
  element.addEventListener("pointerup", (event) => {
    if (!start) return;
    const was_drag = dragging;
    start = last = null;
    dragging = false;
    if (was_drag) return;
    const rect = element.getBoundingClientRect();
    const pointer = new three.Vector2(
      ((event.clientX - rect.left) / rect.width) * 2 - 1,
      -((event.clientY - rect.top) / rect.height) * 2 + 1,
    );
    raycaster.setFromCamera(pointer, orientation.camera);
    const hit = raycaster.intersectObject(orientation.cube)[0];
    const direction = hit && hit.face ? face_view_direction(hit.face.materialIndex) : null;
    if (!direction) return;
    const distance = camera.position.distanceTo(controls.target);
    place_camera(direction.map((value) => value * distance));
  });
  element.addEventListener("pointercancel", () => { start = last = null; dragging = false; });
}
