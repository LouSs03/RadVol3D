// Visor 3D de un estudio: organo semitransparente y una malla opaca por lesion.
// La logica que no dibuja vive en viewer_state.js y tiene sus pruebas (node --test).
// Three.js se importa de forma dinamica: si la red de distribucion no responde, la
// pagina lo dice y ofrece las descargas en lugar de quedar en blanco.
// Convencion del proyecto: snake_case tambien en JavaScript. Los metodos de Three.js
// (setSize, traverse, ...) son de la biblioteca y conservan su nombre.

import {
  ORGAN_COLOR,
  ORGAN_OPACITY,
  confidence_color_hex,
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
const toggle_confidence_button = document.getElementById("toggle_confidence");
const conf_legend = document.getElementById("conf_legend");
const point_tooltip = document.getElementById("point_tooltip");

// Mallas de las lesiones por numero, para resaltarlas desde la lista.
const lesion_meshes = new Map();
let selected_lesion = null;
let show_confidence = false;

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

// ---- Cubo de orientacion anatomica (HU-3.1) ----
// Un cubo en miniatura en la esquina inferior derecha que rota con la escena.
// Cada cara lleva la inicial de una direccion anatomica:
//   R (Right/Derecha), L (Left/Izquierda),
//   S (Superior), I (Inferior),
//   A (Anterior), P (Posterior).
// Convencion del volumen: +X = derecha, +Y = superior, +Z = anterior (hacia el
// observador en la vista inicial). Las etiquetas usan el ingles clinico (R, L, A,
// P, S, I) porque son universales en radiologia.

const ORIENTATION_CUBE_SIZE = 120;

// Colores por cara, accesibles con daltonismo (inspirados en Okabe-Ito).
const ORIENTATION_FACES = [
  { label: "R", color: "#0072B2" },   // +X: Right (Derecha)
  { label: "L", color: "#56B4E9" },   // -X: Left (Izquierda)
  { label: "S", color: "#009E73" },   // +Y: Superior
  { label: "I", color: "#D55E00" },   // -Y: Inferior
  { label: "A", color: "#E69F00" },   // +Z: Anterior
  { label: "P", color: "#CC79A7" },   // -Z: Posterior
];

function face_texture(three, label, bg_color) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  // Fondo de color con borde fino.
  ctx.fillStyle = bg_color;
  ctx.fillRect(0, 0, 128, 128);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.25)";
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, 124, 124);
  // Letra blanca centrada.
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
  if (!container) {
    return null;
  }
  const renderer = new three.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  renderer.setSize(ORIENTATION_CUBE_SIZE, ORIENTATION_CUBE_SIZE);
  container.append(renderer.domElement);

  const scene = new three.Scene();
  scene.add(new three.AmbientLight(0xffffff, 0.7));
  const light = new three.DirectionalLight(0xffffff, 0.6);
  light.position.set(1, 1, 1);
  scene.add(light);

  // Camara ortografica: el cubo se ve siempre del mismo tamano.
  const camera = new three.OrthographicCamera(-1.4, 1.4, 1.4, -1.4, 0.1, 100);

  const materials = ORIENTATION_FACES.map(({ label, color }) =>
    new three.MeshBasicMaterial({ map: face_texture(three, label, color) }),
  );
  const cube = new three.Mesh(new three.BoxGeometry(1, 1, 1), materials);
  scene.add(cube);

  return { renderer, scene, camera };
}

function sync_orientation(three, orientation, main_camera, controls) {
  if (!orientation) {
    return;
  }
  // El cubo copia solo la direccion de la camara principal (sin posicion ni zoom).
  const direction = new three.Vector3()
    .subVectors(main_camera.position, controls.target)
    .normalize()
    .multiplyScalar(3);
  orientation.camera.position.copy(direction);
  orientation.camera.lookAt(0, 0, 0);
  orientation.renderer.render(orientation.scene, orientation.camera);
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
      lesion_meshes.set(row.lesion_number, { object, color: row.color, confidence: row.confidence });
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

  function apply_confidence_colors(enabled) {
    show_confidence = enabled;
    for (const [number, item] of lesion_meshes) {
      const color = enabled && typeof item.confidence === "number"
        ? confidence_color_hex(item.confidence)
        : item.color;
      for (const material of materials_of(item.object)) {
        material.color.set(color);
        if (selected_lesion === number) {
          material.emissive?.set(color);
        }
        material.needsUpdate = true;
      }
    }
    if (conf_legend) conf_legend.classList.toggle("hidden", !enabled);
    if (toggle_confidence_button) {
      toggle_confidence_button.classList.toggle("on", enabled);
      toggle_confidence_button.setAttribute("aria-pressed", String(enabled));
    }
  }

  if (toggle_confidence_button) {
    toggle_confidence_button.addEventListener("click", () => {
      apply_confidence_colors(!show_confidence);
    });
    toggle_confidence_button.classList.remove("hidden");
  }

  // Raycaster para consultar la confianza de un punto seleccionado en el volumen (HU-3.2)
  const raycaster = new three.Raycaster();
  const pointer = new three.Vector2();
  let pointer_down_pos = { x: 0, y: 0 };

  renderer.domElement.addEventListener("pointerdown", (e) => {
    pointer_down_pos = { x: e.clientX, y: e.clientY };
  });

  renderer.domElement.addEventListener("pointerup", (e) => {
    const dist = Math.hypot(e.clientX - pointer_down_pos.x, e.clientY - pointer_down_pos.y);
    if (dist > 5) return;

    const rect = renderer.domElement.getBoundingClientRect();
    pointer.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    pointer.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(pointer, camera);

    const lesion_roots = Array.from(lesion_meshes.values()).map((l) => l.object);
    const hits = raycaster.intersectObjects(lesion_roots, true);

    if (hits.length > 0) {
      const hit = hits[0];
      for (const [number, item] of lesion_meshes) {
        let curr = hit.object;
        let match = false;
        while (curr) {
          if (curr === item.object) { match = true; break; }
          curr = curr.parent;
        }
        if (match) {
          toggle_highlight(number);
          if (point_tooltip) {
            const conf_num = Number(item.confidence).toFixed(2);
            const conf_pct = (item.confidence * 100).toFixed(1);
            point_tooltip.innerHTML = `<strong>Lesión ${number}</strong><br>Confianza: <strong>${conf_num}</strong> (${conf_pct}%)`;
            point_tooltip.style.left = `${e.clientX - rect.left}px`;
            point_tooltip.style.top = `${e.clientY - rect.top}px`;
            point_tooltip.classList.remove("hidden");
          }
          break;
        }
      }
    } else if (point_tooltip) {
      point_tooltip.classList.add("hidden");
    }
  });

  controls.addEventListener("start", () => {
    if (point_tooltip) point_tooltip.classList.add("hidden");
  });

  // Cubo de orientacion anatomica (HU-3.1): se crea una vez y se sincroniza cada frame.
  const orientation = setup_orientation(three);

  window.addEventListener("resize", () => {
    camera.aspect = canvas_box.clientWidth / canvas_box.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(canvas_box.clientWidth, canvas_box.clientHeight);
  });
  renderer.setAnimationLoop(() => {
    controls.update();
    renderer.render(scene, camera);
    sync_orientation(three, orientation, camera, controls);
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
  for (const [number, item] of lesion_meshes) {
    const chosen = selected_lesion === null || number === selected_lesion;
    const base_color = show_confidence && typeof item.confidence === "number"
      ? confidence_color_hex(item.confidence)
      : item.color;
    for (const material of materials_of(item.object)) {
      material.transparent = !chosen;
      material.opacity = chosen ? 1 : DIMMED_OPACITY;
      material.emissive?.set(number === selected_lesion ? base_color : "#000000");
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
