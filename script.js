const RUNPOD_API_KEY = 'rpa_MA050B33NL0623L4WBSWBP0VU77CH9Y00FLWVGH1c6jr3d';
const ENDPOINT_ID = '4qqf6weor3acy0';
const API_URL = `https://api.runpod.ai/v2/${ENDPOINT_ID}`;

let currentFile = null;
let history = [];

// ─────────────────────────────────────────────
// DOM READY — wire up ALL event listeners here
// so functions are guaranteed to exist first
// ─────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {

  // ── Upload zone click → open file picker ──
  const uploadZone = document.getElementById('upload-zone');
  const fileInput  = document.getElementById('file-input');

  uploadZone.addEventListener('click', () => fileInput.click());   // FIX: was inline onclick

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
    if (file && (file.name.endsWith('.glb') || file.name.endsWith('.gltf'))) {
      handleFile(file);
    }
  });

  // ── View toggle buttons ──
  document.getElementById('btn-render').addEventListener('click', () => setView('render'));
  document.getElementById('btn-3d').addEventListener('click',     () => setView('3d'));

  // ── Material preset chips ──
  // FIX: was onclick="selectPreset(this, '...')" inline — now uses data-prompt
  document.querySelectorAll('.preset-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.preset-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById('prompt-input').value = btn.dataset.prompt;
    });
  });

  // ── Suggestion chips ──
  // FIX: was onclick="addSuggestion('...')" inline — now uses data-suggestion
  document.querySelectorAll('.suggestion').forEach(btn => {
    btn.addEventListener('click', () => {
      const input = document.getElementById('prompt-input');
      const val = input.value.trim();
      input.value = val ? val + ', ' + btn.dataset.suggestion : btn.dataset.suggestion;
      input.focus();
    });
  });

  // ── Render button ──
  // FIX: was onclick="triggerRender()" inline
  document.getElementById('render-btn').addEventListener('click', triggerRender);

  // ── Cmd/Ctrl+Enter shortcut ──
  document.getElementById('prompt-input').addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') triggerRender();
  });

  // ── Connection status check ──
  checkConnection();
});

// ─────────────────────────────────────────────
// File handling (shared by click + drop)
// ─────────────────────────────────────────────
function handleFile(file) {
  currentFile = file;
  const zone = document.getElementById('upload-zone');
  zone.classList.add('has-file');
  zone.querySelector('.upload-text').innerHTML =
    `<strong>${file.name}</strong><br><span style="color:var(--text-muted)">Click to change</span>`;
  document.getElementById('file-label').textContent = file.name;

  const url = URL.createObjectURL(file);
  document.getElementById('model-viewer').src = url;
  showToast('Model loaded: ' + file.name);
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
  mv.style.display = view === '3d' ? 'block' : 'none';
  if (view === '3d') mv.style.flex = '1';
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
    if (currentFile) {
      model_base64 = await fileToBase64(currentFile);
    }

    // Submit job
    const submitRes = await fetch(`${API_URL}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RUNPOD_API_KEY}`
      },
      body: JSON.stringify({ input: { prompt, model_base64 } })
    });

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

      if (status.status === 'COMPLETED') {
        result = status.output;
        break;
      } else if (status.status === 'FAILED') {
        throw new Error('Render failed: ' + JSON.stringify(status));
      }

      document.getElementById('render-status').textContent =
        `Running... ${Math.round((Date.now() - start) / 1000)}s`;
    }

    const elapsed = ((Date.now() - start) / 1000).toFixed(1);

    if (result && result.image_base64) {
      const imgUrl = `data:image/png;base64,${result.image_base64}`;
      showResult(imgUrl, prompt, elapsed);
    } else {
      throw new Error('No image returned');
    }

  } catch (err) {
    showToast('Error: ' + err.message);
    console.error(err);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Render';
    stopLoading();
  }
}

// ─────────────────────────────────────────────
// Show result
// ─────────────────────────────────────────────
function showResult(imgUrl, prompt, time) {
  const prevSrc = document.getElementById('render-img').src;

  const renderImg = document.getElementById('render-img');
  renderImg.src = imgUrl;
  renderImg.classList.add('visible');
  document.getElementById('empty-viewer').style.display = 'none';
  setView('render');

  const ri = document.getElementById('result-img');
  ri.src = imgUrl;
  ri.classList.add('loaded');
  document.getElementById('result-placeholder').style.display = 'none';
  document.getElementById('result-time').textContent = `Rendered in ${time}s`;
  document.getElementById('stat-time').textContent = time + 's';

  const dl = document.getElementById('download-btn');
  dl.href = imgUrl;
  dl.classList.add('visible');

  if (prevSrc && prevSrc !== imgUrl && prevSrc !== window.location.href && window.updateCompare) {
    window.updateCompare(prevSrc, imgUrl);
  }

  addHistory(prompt, imgUrl, time);
  showToast(`Done in ${time}s ⚡`);
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
      <div class="history-time">${time}s · 128 samples</div>
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
  [10, 'Submitting to RunPod...'],
  [25, 'Waiting for GPU...'],
  [45, 'Loading 3D scene...'],
  [65, 'Applying materials...'],
  [80, 'Rendering with Cycles...'],
  [95, 'Saving output...'],
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