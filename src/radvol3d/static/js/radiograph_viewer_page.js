// Pagina del visor del modo de una radiografia (radiograph_viewer.html).
// Convencion del proyecto: snake_case tambien en JavaScript.
//
// Replica el visor de cuatro proyecciones de index.html, que no se modifica: las funciones
// de la escena, el cubo de orientacion, los indicadores y los cortes son copias de las de
// ese archivo, con estas diferencias:
// - sin tumores, sin mapa de confianza y sin panel de lesiones (este modo no segmenta);
// - el cubo de orientacion (que gira la reconstruccion) es el de orientation_cube.js, igual
//   que en index.html;
// - los cortes se dibujan con la proporcion real del voxel (no es cubico ni fijo) y la
//   malla ya viene en mm por eje desde el backend.
// La orientacion es la del visor de siempre (volume_orientation.js, importado sin cambios).

import { HOME_DIRECTION, VOLUME_AXES_IN_SCENE, slice_layout } from "./volume_orientation.js";
import { ORIENTATION_FACES, enable_orientation_cube } from "./orientation_cube.js";
import {
  RELATIVE_LABEL,
  field_of_view_text,
  fit_rect,
  other_warnings,
  parse_npy,
  slice_extent,
  slice_position_text,
} from "./radiograph_view.js";

const API = window.location.protocol.startsWith("http") ? window.location.origin : "http://localhost:8000";
// Los mismos valores que el organo del visor de cuatro proyecciones (index.html).
const ORGAN_COLOR = "#CBD5E1";
const ORGAN_OPACITY = 0.35;
const ORIENTATION_CUBE_SIZE = 90;
const SLICE_CANVASES = { axial: "#sl-ax", coronal: "#sl-co", sagittal: "#sl-sa" };
const prefers_less_motion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const $ = (selector) => document.querySelector(selector);
const viewer = {
  code: null, result: null, volume: null,
  three: null, renderer: null, scene: null, camera: null, controls: null, orientation: null,
  root: null, organ: null, organ_material: null, axes: null, home: null,
  opacity: ORGAN_OPACITY, spin: !prefers_less_motion, show_axes: false,
  fps_frames: 0, fps_since: 0,
};

function escape_html(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function study_path(code, suffix = "") {
  return "/studies/" + encodeURIComponent(code) + suffix;
}

// Nunca lanza: devuelve el estado HTTP (0 si no hubo conexion), el cuerpo JSON y el error.
async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(API + path, options);
  } catch {
    return { http_status: 0, ok: false, body: null, error: "No se pudo conectar con el servidor (" + API + ")." };
  }
  let body = null;
  if ((response.headers.get("content-type") || "").includes("application/json")) {
    try { body = await response.json(); } catch { body = null; }
  }
  const detail = body && body.detail;
  const error = response.ok ? null : (typeof detail === "string" ? detail : "El servidor respondió " + response.status + ".");
  return { http_status: response.status, ok: response.ok, body, error };
}

function viewer_message(text, is_error = false, busy = false) {
  const box = $("#vw-msg");
  box.classList.toggle("err", is_error);
  box.innerHTML = text ? (busy ? '<span class="spin"></span>' : "") + "<span>" + escape_html(text) + "</span>" : "";
}

function study_code_from_url() {
  const code = new URLSearchParams(window.location.search).get("code");
  return code && /^[A-Za-z0-9_-]{1,64}$/.test(code) ? code : null;
}

/* ---------------- panel lateral ---------------- */

function decimal(value, digits = 2) {
  return value.toFixed(digits).replace(".", ",");
}

function fill_panels(result) {
  const relative = result.relative_measurements;
  $("#kv-voxel").textContent = result.voxel_mm.map((v) => decimal(v)).join(" × ") + (relative ? " u" : " mm");
  $("#kv-model").textContent = result.model_name === "reconstruction_x2ct" ? "X2CT-GAN" : (result.model_name || "—");
  const input = result.input_size_px;
  $("#kv-input").textContent = input ? input[1] + " × " + input[0] + " px" : "—";
  const inference = result.timings_s && result.timings_s.inferencia;
  $("#kv-time").textContent = typeof inference === "number" ? decimal(inference, 1) + " s" : "—";
  if (relative) {
    $("#rx-relative").innerHTML = "<b>Sin tamaño de píxel:</b> el DICOM no indica cuántos milímetros mide cada píxel. "
      + "El volumen conserva la proporción de la placa, pero las medidas son <b>" + RELATIVE_LABEL + "</b> (u), no centímetros.";
    $("#rx-relative").classList.remove("hidden");
  }
  const warnings = other_warnings(result.warnings, relative);
  if (warnings.length) {
    const list = document.createElement("ul");
    for (const text of warnings) list.append(Object.assign(document.createElement("li"), { textContent: text }));
    $("#rx-warnings").replaceChildren(Object.assign(document.createElement("b"), { textContent: "Avisos de la reconstrucción" }), list);
    $("#rx-warnings").classList.remove("hidden");
  }
  const link = (anchor, item, url) => {
    if (item) $(item).classList.toggle("hidden", !url);
    if (url) $(anchor).href = API + url;
  };
  link("#dl-surface", null, result.surface_url);
  link("#dl-volume", null, result.volume_url);
  link("#dl-nifti", "#li-nifti", result.nifti_url);
  link("#dl-meta", "#li-meta", result.metadata_url);
  if (result.input_image_url) {
    $("#rx-input").src = API + result.input_image_url;
    $("#rx-input").classList.remove("hidden");
  } else {
    $("#rx-input-caption").textContent = "Este estudio no guardó la placa que vio el modelo.";
  }
}

/* ---------------- cortes ortogonales (copia de index.html, con el voxel real) ---------------- */

function value_range(data) {
  let min = Infinity, max = -Infinity;
  for (let i = 0; i < data.length; i++) {
    const v = data[i];
    if (v < min) min = v;
    if (v > max) max = v;
  }
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return { min: 0, max: 1 };
  return { min, max };
}

function draw_slice_placeholders(text) {
  for (const selector of Object.values(SLICE_CANVASES)) {
    const canvas = $(selector);
    const ctx = canvas.getContext("2d");
    ctx.fillStyle = "#080D16";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#64748B";
    ctx.font = '600 11px "Segoe UI",system-ui,sans-serif';
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
  }
}

async function load_volume(url) {
  let npy = null;
  try {
    const response = await fetch(API + url);
    if (response.ok) npy = parse_npy(await response.arrayBuffer());
  } catch {
    npy = null;
  }
  if (!npy || npy.fortran || npy.shape.length !== 3) {
    draw_slice_placeholders("No disponible");
    return;
  }
  viewer.volume = { ...npy, ...value_range(npy.data) };
  $("#kv-fov").textContent = field_of_view_text(npy.shape, viewer.result.voxel_mm, viewer.result.relative_measurements);
  $("#r-sl").disabled = false;
  $("#r-sl").value = 50;
  $("#lb-sl").textContent = slice_position_text(50);
  draw_slices();
}

// Como draw_slice de index.html (convencion de radiologia y bordes rotulados), pero el
// rectangulo donde se dibuja respeta el tamano real del voxel en cada eje.
function draw_slice(canvas, plane, fraction) {
  const { shape, data, min, max } = viewer.volume;
  const { rows, cols, index_of, labels } = slice_layout(plane, shape, fraction);
  const source = document.createElement("canvas");
  source.width = cols; source.height = rows;
  const source_ctx = source.getContext("2d");
  const image = source_ctx.createImageData(cols, rows);
  for (let r = 0; r < rows; r++) {
    for (let k = 0; k < cols; k++) {
      const lum = 255 * (data[index_of(r, k)] - min) / (max - min);
      const q = (r * cols + k) * 4;
      image.data[q] = lum; image.data[q + 1] = lum + 4; image.data[q + 2] = lum + 10; image.data[q + 3] = 255;
    }
  }
  source_ctx.putImageData(image, 0, 0);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#080D16";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const rect = fit_rect(slice_extent(plane, shape, viewer.result.voxel_mm), canvas.width, canvas.height);
  ctx.imageSmoothingEnabled = true;
  ctx.drawImage(source, rect.x, rect.y, rect.width, rect.height);
  ctx.strokeStyle = "rgba(148,163,184,0.22)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(canvas.width / 2, 0); ctx.lineTo(canvas.width / 2, canvas.height);
  ctx.moveTo(0, canvas.height / 2); ctx.lineTo(canvas.width, canvas.height / 2);
  ctx.stroke();
  ctx.fillStyle = "rgba(203,213,225,0.85)";
  ctx.font = '600 9px "Segoe UI",system-ui,sans-serif';
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText(labels.top, canvas.width / 2, 2);
  ctx.textBaseline = "bottom";
  ctx.fillText(labels.bottom, canvas.width / 2, canvas.height - 2);
  ctx.textBaseline = "middle";
  ctx.textAlign = "left";
  ctx.fillText(labels.left, 2, canvas.height / 2);
  ctx.textAlign = "right";
  ctx.fillText(labels.right, canvas.width - 2, canvas.height / 2);
}

function draw_slices() {
  if (!viewer.volume) return;
  const fraction = Number($("#r-sl").value) / 100;
  for (const [plane, selector] of Object.entries(SLICE_CANVASES)) draw_slice($(selector), plane, fraction);
}

$("#r-sl").addEventListener("input", (event) => {
  $("#lb-sl").textContent = slice_position_text(event.target.value);
  draw_slices();
});

/* ---------------- cubo de orientacion (copia de index.html; interaccion en orientation_cube.js) ---------------- */

function face_texture(three, label, bg_color) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = bg_color;
  ctx.fillRect(0, 0, 128, 128);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.25)";
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, 124, 124);
  ctx.fillStyle = "#ffffff";
  ctx.font = "bold 64px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(label, 64, 68);
  const texture = new three.CanvasTexture(canvas);
  texture.colorSpace = three.SRGBColorSpace;
  return texture;
}

function setup_orientation(three) {
  const container = document.getElementById("orientation_cube");
  const renderer = new three.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(ORIENTATION_CUBE_SIZE, ORIENTATION_CUBE_SIZE);
  container.replaceChildren(renderer.domElement);

  const scene = new three.Scene();
  scene.add(new three.AmbientLight(0xffffff, 0.7));
  const light = new three.DirectionalLight(0xffffff, 0.6);
  light.position.set(1, 1, 1);
  scene.add(light);

  const camera = new three.OrthographicCamera(-1.4, 1.4, 1.4, -1.4, 0.1, 100);
  const materials = ORIENTATION_FACES.map(({ label, color }) =>
    new three.MeshBasicMaterial({ map: face_texture(three, label, color) })
  );
  const cube = new three.Mesh(new three.BoxGeometry(1, 1, 1), materials);
  scene.add(cube);
  return { renderer, scene, camera, cube };
}

function sync_orientation(three, orientation, main_camera, controls) {
  if (!orientation || !main_camera || !controls) return;
  const direction = new three.Vector3()
    .subVectors(main_camera.position, controls.target)
    .normalize()
    .multiplyScalar(3);
  orientation.camera.position.copy(direction);
  orientation.camera.lookAt(0, 0, 0);
  orientation.renderer.render(orientation.scene, orientation.camera);
}

/* ---------------- escena 3D (copia de index.html, sin lesiones) ---------------- */

async function ensure_three() {
  const [three, gltf_module, orbit_module] = await Promise.all([
    import("three"),
    import("three/addons/loaders/GLTFLoader.js"),
    import("three/addons/controls/OrbitControls.js"),
  ]);
  const canvas = $("#cv3d");
  let renderer;
  try {
    renderer = new three.WebGLRenderer({ canvas, antialias: true, alpha: true });
  } catch {
    throw new Error("webgl");
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x000000, 0);
  const scene = new three.Scene();
  scene.add(new three.HemisphereLight(0xffffff, 0x1E293B, 1.4));
  const camera = new three.PerspectiveCamera(40, 1, 0.1, 10000);
  // La luz principal viaja con la camara: el lado que se mira siempre queda iluminado.
  const key_light = new three.DirectionalLight(0xffffff, 1.8);
  key_light.position.set(1, 1.5, 2);
  key_light.target.position.set(0, 0, -1);
  camera.add(key_light, key_light.target);
  scene.add(camera);
  const controls = new orbit_module.OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.autoRotate = viewer.spin;
  controls.autoRotateSpeed = 1.4;
  const orientation = setup_orientation(three);
  Object.assign(viewer, { three, GLTFLoader: gltf_module.GLTFLoader, renderer, scene, camera, controls, orientation });
  // Clic en una cara: vista estandar; arrastrar el cubo: gira la reconstruccion.
  enable_orientation_cube(three, orientation, camera, controls, stop_spin);
  new ResizeObserver(resize_viewer).observe(canvas);
  resize_viewer();
}

function resize_viewer() {
  const { renderer, camera } = viewer;
  if (!renderer) return;
  const canvas = $("#cv3d");
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function paint(object, material) {
  object.traverse((child) => {
    if (child.isMesh) {
      if (child.material) [].concat(child.material).forEach((old) => old.dispose());
      child.material = material;
    }
  });
}

function build_scene(organ_object) {
  const three = viewer.three;
  // El paciente de pie y de frente: la cabeza arriba y el frente hacia la camara
  // (volume_orientation.js).
  const root = new three.Group();
  root.quaternion.setFromRotationMatrix(
    new three.Matrix4().makeBasis(...VOLUME_AXES_IN_SCENE.map((axis) => new three.Vector3(...axis))),
  );
  viewer.organ_material = new three.MeshStandardMaterial({
    color: ORGAN_COLOR, transparent: true, opacity: viewer.opacity,
    depthWrite: false, roughness: 0.6, metalness: 0, side: three.DoubleSide,
  });
  paint(organ_object, viewer.organ_material);
  organ_object.renderOrder = 2;
  root.add(organ_object);
  viewer.root = root;
  viewer.organ = organ_object;
  viewer.scene.add(root);
  root.updateMatrixWorld(true);
  frame_camera();
  apply_view_state();
}

// Encuadra el organo completo; si no tiene geometria, toda la escena.
function frame_camera() {
  const { three, camera, controls } = viewer;
  let box = new three.Box3().setFromObject(viewer.organ);
  if (box.isEmpty()) box = new three.Box3().setFromObject(viewer.root);
  const center = box.isEmpty() ? new three.Vector3() : box.getCenter(new three.Vector3());
  const radius = box.isEmpty() ? 50 : Math.max(box.getSize(new three.Vector3()).length() / 2, 1e-3);
  const distance = radius / Math.sin((camera.fov * Math.PI / 180) / 2);
  camera.position.copy(center).addScaledVector(new three.Vector3(...HOME_DIRECTION).normalize(), distance * 1.05);
  camera.near = distance / 100;
  camera.far = distance * 10;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
  viewer.home = { position: camera.position.clone(), target: center.clone() };
  // Los ejes del volumen giran con el: rojo = derecha del paciente, verde = adelante,
  // azul = cabeza.
  viewer.axes = new three.AxesHelper(radius * 1.1);
  viewer.axes.position.copy(viewer.root.worldToLocal(center.clone()));
  viewer.root.add(viewer.axes);
}

function apply_view_state() {
  if (viewer.organ_material) viewer.organ_material.opacity = viewer.opacity;
  if (viewer.axes) viewer.axes.visible = viewer.show_axes;
  if (viewer.controls) viewer.controls.autoRotate = viewer.spin;
}

function render_frame(time) {
  const { controls, renderer, scene, camera, three, orientation } = viewer;
  controls.update();
  renderer.render(scene, camera);
  sync_orientation(three, orientation, camera, controls);
  viewer.fps_frames++;
  if (!viewer.fps_since) viewer.fps_since = time;
  if (time - viewer.fps_since >= 500) {
    $("#ov-fps").textContent = Math.round(viewer.fps_frames * 1000 / (time - viewer.fps_since)) + " FPS";
    viewer.fps_frames = 0;
    viewer.fps_since = time;
    let azimuth = Math.round(controls.getAzimuthalAngle() * 180 / Math.PI);
    if (azimuth < 0) azimuth += 360;
    const elevation = Math.round(90 - controls.getPolarAngle() * 180 / Math.PI);
    $("#ov-rot").textContent = "Az " + azimuth + "° · El " + elevation + "°";
  }
}

/* ---------------- controles (copia de index.html, sin tumor ni confianza) ---------------- */

// Al usar el cubo la rotacion automatica se apaga, para que la vista elegida quede quieta.
function stop_spin() {
  viewer.spin = false;
  set_toggle("#t-spin", false);
  apply_view_state();
}

function set_toggle(selector, on) {
  const el = $(selector);
  el.classList.toggle("on", on);
  el.setAttribute("aria-pressed", String(on));
}

function bind_toggle(selector, apply) {
  const el = $(selector);
  el.addEventListener("click", () => {
    const on = !el.classList.contains("on");
    set_toggle(selector, on);
    apply(on);
    apply_view_state();
  });
}
bind_toggle("#t-spin", (on) => { viewer.spin = on; });
bind_toggle("#t-axes", (on) => { viewer.show_axes = on; });
set_toggle("#t-spin", viewer.spin);

$("#r-op").addEventListener("input", (event) => {
  const value = Number(event.target.value);
  $("#lb-op").textContent = value + " %";
  viewer.opacity = value / 100;
  apply_view_state();
});

// "Tejido" es el unico modo de este visor (no hay tumores): deja el organo con la
// opacidad elegida.
$(".vtools button[data-mode='tissue']").addEventListener("click", apply_view_state);

$("#btn-home-view").addEventListener("click", () => {
  if (!viewer.home) return;
  viewer.camera.position.copy(viewer.home.position);
  viewer.controls.target.copy(viewer.home.target);
  viewer.controls.update();
});

$("#btn-delete").addEventListener("click", async () => {
  const code = viewer.code;
  if (!code || !window.confirm("¿Eliminar el estudio " + code + " con todos sus archivos? No se puede deshacer.")) return;
  const { ok, http_status, error } = await api(study_path(code), { method: "DELETE" });
  if (!ok && http_status !== 404) { window.alert(error); return; }
  window.location.href = "/static/#/history";
});

/* ---------------- arranque ---------------- */

async function start() {
  const code = study_code_from_url();
  draw_slice_placeholders("Cargando…");
  if (!code) {
    viewer_message("Falta el código del estudio. Ábrelo desde el historial.", true);
    draw_slice_placeholders("No disponible");
    return;
  }
  viewer.code = code;
  document.querySelectorAll(".times-link").forEach((a) => { a.href = "/static/#/metrics/" + encodeURIComponent(code); });
  $("#ov-case").textContent = "Estudio " + code;
  viewer_message("Consultando el estudio…", false, true);

  const status = await api(study_path(code, "/status"));
  if (status.http_status === 404) {
    viewer_message("El estudio " + code + " no existe.", true);
    draw_slice_placeholders("No disponible");
    return;
  }
  if (!status.body) { viewer_message(status.error, true); return; }
  if (status.body.input_mode !== "radiograph") {
    window.location.replace("/static/#/viewer/" + encodeURIComponent(code));
    return;
  }
  const organ_label = { lung: "Pulmón", liver: "Hígado" }[status.body.organ] || status.body.organ;
  $("#vw-title").textContent = "Reconstrucción volumétrica · " + organ_label;
  $("#ov-organ").textContent = organ_label;
  if (status.body.status !== "completed") {
    const text = { pending: "todavía no se procesó", processing: "se está procesando", failed: "falló al procesarse" }[status.body.status] || status.body.status;
    viewer_message("El estudio " + code + " " + text + ". El visor se habilita cuando termina.", status.body.status === "failed");
    draw_slice_placeholders("No disponible");
    return;
  }

  const result = await api(study_path(code, "/radiograph-result"));
  if (!result.ok) { viewer_message(result.error, true); return; }
  viewer.result = result.body;
  if (viewer.result.model_name && viewer.result.model_name !== "reconstruction_x2ct") {
    $("#ov-input").textContent = "1 radiografía · AXON";
  }
  fill_panels(viewer.result);
  load_volume(viewer.result.volume_url);

  viewer_message("Cargando el visor 3D…", false, true);
  try {
    await ensure_three();
  } catch (problem) {
    viewer_message(problem && problem.message === "webgl"
      ? "Este navegador no puede dibujar 3D (WebGL). Puedes descargar la superficie."
      : "No se pudo cargar Three.js desde la red. Puedes descargar la superficie.", true);
    return;
  }
  viewer_message("Descargando la superficie…", false, true);
  let gltf;
  try {
    gltf = await new viewer.GLTFLoader().loadAsync(API + viewer.result.surface_url);
  } catch {
    viewer_message("No se pudo cargar la superficie del estudio. Puedes descargarla.", true);
    return;
  }
  build_scene(gltf.scene);
  viewer_message("");
  resize_viewer();
  viewer.renderer.setAnimationLoop(render_frame);
}

start();
