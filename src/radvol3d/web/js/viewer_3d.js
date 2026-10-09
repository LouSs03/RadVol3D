// Visor 3D de un estudio: organo semitransparente y una malla opaca por lesion.
// La logica que no dibuja vive en viewer_state.js y tiene sus pruebas (node --test).
// Three.js se importa de forma dinamica: si la red de distribucion no responde, la
// pagina lo dice y ofrece las descargas en lugar de quedar en blanco.
// Convencion del proyecto: snake_case tambien en JavaScript. Los metodos de Three.js
// (setSize, traverse, ...) son de la biblioteca y conservan su nombre.

import {
  ORGAN_COLOR,
  ORGAN_OPACITY,
  lesion_rows,
  status_view,
  study_code_from_path,
} from "/js/viewer_state.js";

const DIMMED_OPACITY = 0.25;
const HIGHLIGHT_INTENSITY = 0.6;
const number_format = new Intl.NumberFormat("es", { maximumFractionDigits: 2 });
const percent_format = new Intl.NumberFormat("es", { style: "percent", maximumFractionDigits: 1 });

const study_code = study_code_from_path(window.location.pathname);
const canvas_box = document.getElementById("viewer_canvas");
const status_box = document.getElementById("status_message");
const reset_button = document.getElementById("reset_view");

// Mallas de las lesiones por numero, para resaltarlas desde la lista.
const lesion_meshes = new Map();
let selected_lesion = null;

function show_message(text) {
  status_box.textContent = text;
  status_box.classList.toggle("hidden", !text);
}

function reveal(element_id) {
  document.getElementById(element_id).classList.remove("hidden");
}

async function fetch_json(url) {
  const response = await fetch(url);
  let body = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  return { http_status: response.status, body };
}

function study_url(suffix) {
  return `/studies/${encodeURIComponent(study_code)}${suffix}`;
}

async function check_status() {
  if (study_code === null) {
    show_message("La dirección no trae el código del estudio.");
    return;
  }
  document.getElementById("study_title").textContent = `Estudio ${study_code}`;
  const { http_status, body } = await fetch_json(study_url("/status"));
  const view = status_view(http_status, body);
  show_message(view.message);
  if (view.action === "refresh") {
    window.setTimeout(check_status, view.refresh_ms);
  } else if (view.action === "load") {
    await load_result();
  }
}

async function load_result() {
  const { http_status, body } = await fetch_json(study_url("/result"));
  if (http_status !== 200) {
    show_message(body?.detail ?? "No se pudo leer el resultado del estudio.");
    return;
  }
  const rows = lesion_rows(body);
  fill_downloads(body);
  fill_lesion_list(rows);

  let modules;
  try {
    modules = await load_three();
  } catch {
    show_message("No se pudo cargar Three.js desde la red. Puedes descargar las mallas.");
    reveal("downloads");
    return;
  }
  if (!webgl_available()) {
    show_message("Este navegador no puede dibujar 3D (WebGL). Puedes descargar las mallas.");
    reveal("downloads");
    return;
  }
  await build_scene(modules, body, rows);
}

async function load_three() {
  const three = await import("three");
  const { GLTFLoader } = await import("three/addons/loaders/GLTFLoader.js");
  const { OrbitControls } = await import("three/addons/controls/OrbitControls.js");
  return { three, GLTFLoader, OrbitControls };
}

function webgl_available() {
  const probe = document.createElement("canvas");
  return Boolean(probe.getContext("webgl2") || probe.getContext("webgl"));
}

function fill_downloads(result) {
  document.getElementById("organ_link").href = result.organ_mesh_url;
  document.getElementById("tumor_link").href = result.tumor_mesh_url;
  document.getElementById("volume_link").href = result.volume_url;
  reveal("downloads");
}

function fill_lesion_list(rows) {
  if (rows.length === 0) {
    reveal("no_lesions");
    return;
  }
  const body = document.getElementById("lesion_rows");
  for (const row of rows) {
    const line = document.createElement("tr");
    line.className = "lesion_row";
    line.tabIndex = 0;
    line.dataset.lesion_number = String(row.lesion_number);

    const swatch = document.createElement("span");
    swatch.className = "color_swatch";
    swatch.style.backgroundColor = row.color;
    const link = document.createElement("a");
    link.href = row.mesh_url;
    link.textContent = ".glb";
    link.setAttribute("download", "");

    const cells = [
      swatch,
      String(row.lesion_number),
      row.organ ?? "—",
      row.location,
      number_format.format(row.volume_mm3),
      typeof row.max_diameter_mm === "number"
        ? number_format.format(row.max_diameter_mm)
        : row.max_diameter_mm,
      percent_format.format(row.confidence),
      link,
    ];
    for (const content of cells) {
      const cell = document.createElement("td");
      if (typeof content === "string") {
        cell.textContent = content;
      } else {
        cell.append(content);
      }
      line.append(cell);
    }
    line.addEventListener("click", () => toggle_highlight(row.lesion_number));
    line.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle_highlight(row.lesion_number);
      }
    });
    body.append(line);
  }
  reveal("lesion_table");
}

function materials_of(object) {
  const materials = [];
  object.traverse((child) => {
    if (child.isMesh) {
      materials.push(child.material);
    }
  });
  return materials;
}

function paint(three, object, options) {
  object.traverse((child) => {
    if (child.isMesh) {
      child.material = new three.MeshStandardMaterial(options);
    }
  });
}

async function build_scene(modules, result, rows) {
  const { three, GLTFLoader, OrbitControls } = modules;
  const renderer = new three.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(canvas_box.clientWidth, canvas_box.clientHeight);
  canvas_box.append(renderer.domElement);

  const scene = new three.Scene();
  scene.add(new three.AmbientLight(0xffffff, 0.6));
  const light = new three.DirectionalLight(0xffffff, 1.2);
  light.position.set(1, 1, 1);
  scene.add(light);

  const camera = new three.PerspectiveCamera(
    45,
    canvas_box.clientWidth / canvas_box.clientHeight,
    0.1,
    10000,
  );
  const controls = new OrbitControls(camera, renderer.domElement);
  const loader = new GLTFLoader();

  let organ;
  try {
    organ = (await loader.loadAsync(result.organ_mesh_url)).scene;
    const lesions = await Promise.all(rows.map((row) => loader.loadAsync(row.mesh_url)));
    rows.forEach((row, index) => {
      const object = lesions[index].scene;
      paint(three, object, { color: row.color });
      object.renderOrder = 1;
      scene.add(object);
      lesion_meshes.set(row.lesion_number, { object, color: row.color });
    });
  } catch {
    show_message("No se pudieron cargar las mallas. Puedes descargarlas.");
    return;
  }
  // El organo al final y sin escribir profundidad: asi las lesiones se ven a traves.
  paint(three, organ, {
    color: ORGAN_COLOR,
    transparent: true,
    opacity: ORGAN_OPACITY,
    depthWrite: false,
  });
  organ.renderOrder = 2;
  scene.add(organ);

  const initial_view = frame_view(three, camera, controls, organ, scene);
  reset_button.addEventListener("click", () => {
    camera.position.copy(initial_view.position);
    controls.target.copy(initial_view.target);
    controls.update();
  });
  reset_button.classList.remove("hidden");

  window.addEventListener("resize", () => {
    camera.aspect = canvas_box.clientWidth / canvas_box.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(canvas_box.clientWidth, canvas_box.clientHeight);
  });
  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
  });
  show_message("");
}

// La vista inicial encuadra el organo completo. Si el organo no tiene geometria
// (volumen constante), encuadra toda la escena.
function frame_view(three, camera, controls, organ, scene) {
  let box = new three.Box3().setFromObject(organ);
  if (box.isEmpty()) {
    box = new three.Box3().setFromObject(scene);
  }
  const center = box.isEmpty() ? new three.Vector3() : box.getCenter(new three.Vector3());
  const size = box.isEmpty() ? 100 : box.getSize(new three.Vector3()).length();
  const distance = size / (2 * Math.tan((camera.fov * Math.PI) / 360));
  camera.position.copy(center).add(new three.Vector3(0, 0, distance * 1.1));
  camera.near = Math.max(distance / 100, 0.1);
  camera.far = distance * 10;
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
  return { position: camera.position.clone(), target: center.clone() };
}

// Elegir una fila resalta su malla y baja la opacidad de las demas; otro clic lo deshace.
function toggle_highlight(lesion_number) {
  selected_lesion = selected_lesion === lesion_number ? null : lesion_number;
  for (const [number, { object, color }] of lesion_meshes) {
    const chosen = selected_lesion === null || number === selected_lesion;
    for (const material of materials_of(object)) {
      material.transparent = !chosen;
      material.opacity = chosen ? 1 : DIMMED_OPACITY;
      material.emissive?.set(number === selected_lesion ? color : "#000000");
      material.emissiveIntensity = number === selected_lesion ? HIGHLIGHT_INTENSITY : 0;
      material.needsUpdate = true;
    }
  }
  for (const line of document.querySelectorAll(".lesion_row")) {
    line.classList.toggle(
      "lesion_row_selected",
      Number(line.dataset.lesion_number) === selected_lesion,
    );
  }
}

check_status();
