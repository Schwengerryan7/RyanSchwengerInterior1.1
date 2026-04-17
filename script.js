const RUNPOD_API_KEY = 'YOUR_NEW_KEY_HERE';
const ENDPOINT_ID = '4qqf6weor3acy0';
const API_URL = `https://cautious-journey-69jrr96g77642rpq4-3001.app.github.dev`;

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
    // FIX: accept .ply in addition to .glb / .gltf
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
// File handling (shared by click + drop)
// ─────────────────────────────────────────────
function handleFile(file) {
  currentFile = file;
  const zone = document.getElementById('upload-zone');
  zone.classList.add('has-file');
  zone.querySelector('.upload-text').innerHTML =
    `<strong>${file.name}</strong><br><span style="color:var(--text-muted)">Click to change</span>`;
  document.getElementById('file-label').textContent = file.name;

  // Only load into 3D viewer if it's a GLB/GLTF (model-viewer can't show PLY)
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
    // FIX: detect PLY vs GLB and send to correct handler key
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
      // FIX: include both keys so handler picks the right path
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

      // Load GLB into model-viewer for interactive 3D rotation
      if (result.mesh_base64) {
        console.log('[3D] GLB received, loading into model-viewer...');
        const glbBlob = new Blob(
          [Uint8Array.from(atob(result.mesh_base64), c => c.charCodeAt(0))],
          { type: 'model/gltf-binary' }
        );
        const glbUrl = URL.createObjectURL(glbBlob);
        const mv = document.getElementById('model-viewer');
        mv.src = glbUrl;
        mv.setAttribute('auto-rotate', '');
        mv.setAttribute('camera-controls', '');
        mv.setAttribute('shadow-intensity', '1');
        // Auto-switch to 3D view after short delay so render shows first
        setTimeout(() => setView('3d'), 1500);
        showToast('3D model loaded — drag to rotate!');
      } else {
        console.log('[3D] No mesh_base64 in response — GLB was too large or export failed');
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
  if (ri) {
    ri.src = imgUrl;
    ri.classList.add('loaded');
  }
  const rp = document.getElementById('result-placeholder');
  if (rp) rp.style.display = 'none';

  const rt = document.getElementById('result-time');
  if (rt) rt.textContent = `Rendered in ${time}s`;
  const st = document.getElementById('stat-time');
  if (st) st.textContent = time + 's';

  const dl = document.getElementById('download-btn');
  if (dl) {
    dl.href = imgUrl;
    dl.classList.add('visible');
  }

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
