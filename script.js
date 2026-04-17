const RUNPOD_API_KEY = 'YOUR_NEW_KEY_HERE';
const ENDPOINT_ID = '4qqf6weor3acy0';
const API_URL = `https://cautious-journey-69jrr96g77642rpq4-3001.app.github.dev`;

let currentFile = null;
let history = [];

// ─────────────────────────────────────────────
// DOM READY — wire up ALL event listeners here
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // ── Upload zone click → open file picker ──
  const uploadZone = document.getElementById('upload-zone');
  const fileInput  = document.getElementById('file-input');

  uploadZone.addEventListener('click', () => fileInput.click());

  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    handleFile(file);
  });

  // ── Drag & drop ──
  uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.style.borderColor = 'var(--text)';
  });
  uploadZone.addEventListener('dragleave', () => {
    uploadZone.style.borderColor = '';
  });
  uploadZone.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadZone.style.borderColor = '';
    const file = e.dataTransfer.files[0];
    if (file && (file.name.endsWith('.glb') || file.name.endsWith('.gltf') || file.name.endsWith('.ply'))) {
      handleFile(file);
    }
  });

  // ── View toggle buttons ──
  document.getElementById('btn-render').addEventListener('click', () => setView('render'));
  document.getElementById('btn-3d').addEventListener('click',     () => setView('3d'));

  // ── Material preset chips ──
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('prompt-input').value = btn.dataset.prompt;
    });
  });

  // ── Suggestion chips ──
  document.querySelectorAll('.suggestion').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById('prompt-input');
      const val = input.value.trim();
      input.value = val ? val + ', ' + btn.dataset.suggestion : btn.dataset.suggestion;
      input.focus();
    });
  });

  // ── Render button ──
  document.getElementById('render-btn').addEventListener('click', triggerRender);

  // ── Cmd/Ctrl+Enter shortcut ──
  document.getElementById('prompt-input').addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') triggerRender();
  });

  // ── Connection status check ──
  checkConnection();
});

// ─────────────────────────────────────────────
// File handling
// ─────────────────────────────────────────────
function handleFile(file) {
  currentFile = file;
  _3dViewerReady = false; // reset 3D viewer for new file
  const zone = document.getElementById('upload-zone');
  zone.classList.add('has-file');
  zone.querySelector('.upload-text').innerHTML =
    `<strong>${file.name}</strong><br><span style="color:var(--text-muted)">Click to change</span>`;
  document.getElementById('file-label').textContent = file.name;

  // Only load into model-viewer if it's a GLB/GLTF
  if (!file.name.toLowerCase().endsWith('.ply')) {
    const url = URL.createObjectURL(file);
    document.getElementById('model-viewer').src = url;
  }
  showToast('File loaded: ' + file.name);
}

// ─────────────────────────────────────────────
// View toggle
// ─────────────────────────────────────────────
function setView(view) {
  const rv = document.getElementById('render-view');
  const mv = document.getElementById('model-viewer');
  document.getElementById('btn-render').classList.toggle('active', view === 'render');
  document.getElementById('btn-3d').classList.toggle('active', view === '3d');
  rv.style.display = view === 'render' ? 'flex' : 'none';

  if (view === '3d' && currentFile && currentFile.name.toLowerCase().endsWith('.ply')) {
    // Use our own Three.js div, hide model-viewer
    if (mv) mv.style.display = 'none';
    let pv = document.getElementById('ply-viewer');
    if (!pv) {
      pv = document.createElement('div');
      pv.id = 'ply-viewer';
      pv.style.cssText = 'width:100%;flex:1;min-height:420px;display:block;';
      mv ? mv.parentNode.insertBefore(pv, mv) : document.body.appendChild(pv);
    }
    pv.style.display = 'block';
    init3DViewer(pv);
  } else {
    const pv = document.getElementById('ply-viewer');
    if (pv) pv.style.display = 'none';
    if (mv) { mv.style.display = view === '3d' ? 'block' : 'none'; mv.style.flex = '1'; }
  }
}

// ─────────────────────────────────────────────
// Three.js PLY 3D viewer
// ─────────────────────────────────────────────
let _3dViewerReady = false;

function init3DViewer(container) {
  if (_3dViewerReady) return;

  container.innerHTML = '';
  const canvas = document.createElement('canvas');
  canvas.style.cssText = 'width:100%;height:100%;display:block;';
  container.appendChild(canvas);

  function loadScript(src, cb) {
    const s = document.createElement('script'); s.src = src; s.onload = cb; document.head.appendChild(s);
  }

  const THREE_CDN = 'https://cdn.jsdelivr.net/npm/three@0.158.0/build/three.min.js';
  const PLY_CDN   = 'https://cdn.jsdelivr.net/npm/three@0.158.0/examples/js/loaders/PLYLoader.js';
  const ORBIT_CDN = 'https://cdn.jsdelivr.net/npm/three@0.158.0/examples/js/controls/OrbitControls.js';

  function startViewer() {
    const THREE = window.THREE;
    const w = container.clientWidth  || 600;
    const h = container.clientHeight || 600;

    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(w, h);
    renderer.setClearColor(0x1a1a2e);

    const scene  = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, w / h, 0.01, 100);
    camera.position.set(0, 1, 3);

    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping   = true;
    controls.dampingFactor   = 0.08;
    controls.autoRotate      = true;
    controls.autoRotateSpeed = 1.5;
    controls.target.set(0, 0, 0);

    // Lights
    scene.add(new THREE.AmbientLight(0xffffff, 0.7));
    const sun = new THREE.DirectionalLight(0xfff5e0, 1.8);
    sun.position.set(3, 6, 4); scene.add(sun);
    const fill = new THREE.DirectionalLight(0xe0f0ff, 0.6);
    fill.position.set(-3, 2, -2); scene.add(fill);

    // Load PLY
    const loader = new THREE.PLYLoader();
    loader.load(URL.createObjectURL(currentFile), (geo) => {
      geo.computeVertexNormals();
      geo.computeBoundingBox();
      const box  = geo.boundingBox;
      const cx   = (box.min.x + box.max.x) / 2;
      const cy   = (box.min.y + box.max.y) / 2;
      const cz   = (box.min.z + box.max.z) / 2;
      const size = Math.max(box.max.x - box.min.x, box.max.y - box.min.y, box.max.z - box.min.z);
      geo.translate(-cx, -cy, -cz);
      const scale = 2 / (size || 1);

      const mat = new THREE.MeshStandardMaterial({
        color: geo.hasAttribute('color') ? 0xffffff : 0xc4a570,
        vertexColors: geo.hasAttribute('color'),
        roughness: 0.65,
        metalness: 0.05,
      });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.scale.setScalar(scale);
      mesh.rotation.x = -Math.PI / 2; // PLY Y-up → Z-up
      scene.add(mesh);
      controls.update();
      _3dViewerReady = true;
      showToast('Drag to rotate • Scroll to zoom');
    });

    (function animate() {
      requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    })();
  }

  if (window.THREE && window.THREE.PLYLoader && window.THREE.OrbitControls) {
    startViewer();
  } else if (window.THREE) {
    loadScript(PLY_CDN, () => loadScript(ORBIT_CDN, startViewer));
  } else {
    loadScript(THREE_CDN, () => loadScript(PLY_CDN, () => loadScript(ORBIT_CDN, startViewer)));
  }
}

// ─────────────────────────────────────────────
// File → base64
// ─────────────────────────────────────────────
async function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload  = () => resolve(reader.result.split(',')[1]);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

// ─────────────────────────────────────────────
// Render
// ─────────────────────────────────────────────
async function triggerRender() {
  const prompt = document.getElementById('prompt-input').value.trim();
  if (!prompt) { showToast('Enter a prompt first'); return; }

  const btn = document.getElementById('render-btn');
  btn.disabled = true;
  btn.textContent = 'Rendering...';
  startLoading();

  try {
    let model_base64 = null;
    let ply_base64 = null;
    if (currentFile) {
      const b64 = await fileToBase64(currentFile);
      if (currentFile.name.toLowerCase().endsWith('.ply')) {
        ply_base64 = b64;
      } else {
        model_base64 = b64;
      }
    }

    // Submit job
    const submitRes = await fetch(`${API_URL}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RUNPOD_API_KEY}`
      },
      body: JSON.stringify({ input: { prompt, model_base64, ply_base64 } })
    });

    if (!submitRes.ok) {
      const errText = await submitRes.text();
      throw new Error(`RunPod ${submitRes.status}: ${errText.slice(0, 300)}`);
    }
    const job = await submitRes.json();
    const jobId = job.id;
    showToast('Job submitted — waiting for GPU...');

    // Poll for result
    const start = Date.now();
    let result = null;
    while (true) {
      await new Promise(r => setTimeout(r, 3000));
      const statusRes = await fetch(`${API_URL}/status/${jobId}`, {
        headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
      });
      const status = await statusRes.json();

      const elapsed = Math.round((Date.now() - start) / 1000);
      document.getElementById('render-status').textContent = `Running... ${elapsed}s`;
      console.log(`RunPod /status: ${statusRes.status}`, status);

      if (status.status === 'COMPLETED') {
        result = status.output;
        break;
      } else if (status.status === 'FAILED') {
        throw new Error('Render failed: ' + JSON.stringify(status));
      }
    }

    const elapsed = ((Date.now() - start) / 1000).toFixed(1);

    if (result && result.image_base64) {
      const imgUrl = `data:image/png;base64,${result.image_base64}`;

      // Build carousel: main view + alt views
      const allImages = [imgUrl];
      if (result.alt_images && result.alt_images.length > 0) {
        result.alt_images.forEach(b64 => allImages.push(`data:image/jpeg;base64,${b64}`));
      }
      showResult(imgUrl, prompt, elapsed, allImages);

      // Auto-open 3D viewer after 2s if PLY was uploaded
      if (currentFile && currentFile.name.toLowerCase().endsWith('.ply')) {
        setTimeout(() => setView('3d'), 2000);
      }

      if (result.claude_notes && result.claude_notes.length > 0) {
        console.log('[Claude notes]', result.claude_notes);
      }
    } else if (result && result.error) {
      throw new Error('Render error: ' + result.error);
    } else {
      throw new Error('No image returned: ' + JSON.stringify(result));
    }

  } catch (err) {
    showToast('Error: ' + err.message);
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Reconstruct & Render';
    stopLoading();
  }
}

// ─────────────────────────────────────────────
// Show result
// ─────────────────────────────────────────────
function showResult(imgUrl, prompt, time, allImages) {
  const prevSrc = document.getElementById('render-img').src;

  const renderImg = document.getElementById('render-img');
  renderImg.src = imgUrl;
  renderImg.classList.add('visible');
  document.getElementById('empty-viewer').style.display = 'none';
  setView('render');

  // ── Carousel for multi-angle views ──────────────────────────────────────────
  if (allImages && allImages.length > 1) {
    let carouselEl = document.getElementById('angle-carousel');
    if (!carouselEl) {
      carouselEl = document.createElement('div');
      carouselEl.id = 'angle-carousel';
      carouselEl.style.cssText = 'display:flex;gap:8px;padding:8px 0;justify-content:center;';
      renderImg.parentElement.appendChild(carouselEl);
    }
    carouselEl.innerHTML = '';
    allImages.forEach((url, i) => {
      const thumb = document.createElement('img');
      thumb.src = url;
      thumb.style.cssText = `width:72px;height:72px;object-fit:cover;border-radius:6px;cursor:pointer;border:2px solid ${i===0?'var(--accent)':'transparent'};`;
      thumb.addEventListener('click', () => {
        renderImg.src = url;
        carouselEl.querySelectorAll('img').forEach(t => t.style.borderColor = 'transparent');
        thumb.style.borderColor = 'var(--accent)';
      });
      carouselEl.appendChild(thumb);
    });
  }

  const ri = document.getElementById('result-img');
  if (ri) { ri.src = imgUrl; ri.classList.add('loaded'); }
  const rp = document.getElementById('result-placeholder');
  if (rp) rp.style.display = 'none';

  const rt = document.getElementById('result-time');
  if (rt) rt.textContent = `Rendered in ${time}s`;
  const st = document.getElementById('stat-time');
  if (st) st.textContent = time + 's';

  const dl = document.getElementById('download-btn');
  if (dl) { dl.href = imgUrl; dl.classList.add('visible'); }

  if (prevSrc && prevSrc !== imgUrl && prevSrc !== window.location.href && window.updateCompare) {
    window.updateCompare(prevSrc, imgUrl);
  }

  addHistory(prompt, imgUrl, time);
  showToast(`Done in ${time}s`);
}

// ─────────────────────────────────────────────
// History
// ─────────────────────────────────────────────
function addHistory(prompt, imgUrl, time) {
  const list = document.getElementById('history-list');
  if (history.length === 0) list.innerHTML = '';
  history.unshift({ prompt, imgUrl, time });

  const item = document.createElement('div');
  item.className = 'history-item active';
  item.innerHTML = `
    <div class="history-thumb">${imgUrl ? `<img src="${imgUrl}">` : '🪑'}</div>
    <div class="history-info">
      <div class="history-prompt">${prompt}</div>
      <div class="history-time">${time}s · 512 samples</div>
    </div>
  `;
  item.addEventListener('click', () => {
    document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
    item.classList.add('active');
    if (imgUrl) {
      document.getElementById('render-img').src = imgUrl;
      document.getElementById('render-img').classList.add('visible');
      document.getElementById('empty-viewer').style.display = 'none';
      setView('render');
    }
  });
  document.querySelectorAll('.history-item').forEach(i => i.classList.remove('active'));
  list.prepend(item);
}

// ─────────────────────────────────────────────
// Loading overlay
// ─────────────────────────────────────────────
const loadingSteps = [
  [10,  'Submitting to RunPod...'],
  [20,  'Waiting for GPU worker...'],
  [35,  'Open3D point cloud reconstruction...'],
  [50,  'Loading 3D scene in Blender...'],
  [65,  'Applying materials & zones...'],
  [75,  'Preview render (128 samples)...'],
  [85,  'Claude vision analysis...'],
  [93,  'Final render (512 samples)...'],
  [98,  'Saving output...'],
];
let loadingTimer;

function startLoading() {
  document.getElementById('render-overlay').classList.add('active');
  let i = 0;
  loadingTimer = setInterval(() => {
    if (i < loadingSteps.length) {
      document.getElementById('progress-bar').style.width = loadingSteps[i][0] + '%';
      document.getElementById('render-status').textContent = loadingSteps[i][1];
      i++;
    }
  }, 2000);
}

function stopLoading() {
  clearInterval(loadingTimer);
  document.getElementById('progress-bar').style.width = '100%';
  setTimeout(() => {
    document.getElementById('render-overlay').classList.remove('active');
    document.getElementById('progress-bar').style.width = '0%';
  }, 400);
}

// ─────────────────────────────────────────────
// Connection check
// ─────────────────────────────────────────────
async function checkConnection() {
  try {
    const res = await fetch(`${API_URL}/health`, {
      headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
    });
    if (res.ok) {
      document.getElementById('conn-dot').classList.add('connected');
      document.getElementById('conn-label').textContent = 'Connected';
    }
  } catch {
    document.getElementById('conn-label').textContent = 'Not connected';
  }
}

// ─────────────────────────────────────────────
// Toast
// ─────────────────────────────────────────────
function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}
