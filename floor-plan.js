(function () {
  'use strict';

  // API base — picks up the same URL script.js uses
  const API_BASE = (typeof API_URL !== 'undefined' ? API_URL : 'http://localhost:3001');

  // Demo 2-bed apartment (10m × 8m, coordinates in cm, scale=100 cm/m)
  const DEMO = {
    width: 1000, height: 800, scale: 100,
    rooms: [
      { label: 'Living / Dining', area: 30, color: '#f5f0e8',
        poly: [[0,0],[600,0],[600,500],[0,500]] },
      { label: 'Kitchen',         area: 12, color: '#eaf0e8',
        poly: [[600,0],[1000,0],[1000,300],[600,300]] },
      { label: 'Master Bedroom',  area: 20, color: '#e8eaf5',
        poly: [[600,300],[1000,300],[1000,800],[600,800]] },
      { label: 'Bedroom',         area: 12, color: '#e8eaf5',
        poly: [[0,500],[400,500],[400,800],[0,800]] },
      { label: 'Bathroom',        area: 5,  color: '#ddf0ec',
        poly: [[400,500],[600,500],[600,750],[400,750]] },
      { label: 'Entry',           area: 1,  color: '#eeece8',
        poly: [[400,750],[600,750],[600,800],[400,800]] },
    ],
    walls: [
      [[0,0],[1000,0]], [[1000,0],[1000,800]],
      [[1000,800],[0,800]], [[0,800],[0,0]],
      [[600,0],[600,800]], [[0,500],[600,500]],
      [[400,500],[400,800]], [[600,300],[1000,300]],
      [[400,750],[600,750]],
    ],
    doors: [
      { hinge: [460,0],   len: 90, dir: Math.PI / 2 },
      { hinge: [600,120], len: 80, dir: 0 },
      { hinge: [780,300], len: 80, dir: Math.PI / 2 },
      { hinge: [100,500], len: 80, dir: Math.PI / 2 },
      { hinge: [400,580], len: 70, dir: 0 },
    ],
  };

  let canvas, ctx;
  let plan = null;
  let tx = 0, ty = 0, tscale = 1;
  let panning = false, panStart = null;
  let generating = false;
  let _pendingPlyFile = null;
  let viewMode = '2d';       // '2d' | '3d'
  let three = null;          // Three.js state

  function init() {
    canvas = document.getElementById('fp-canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    window.addEventListener('resize', resize);

    canvas.addEventListener('wheel',     onWheel,     { passive: false });
    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup',   onMouseUp);
    canvas.addEventListener('mouseleave',onMouseUp);
    canvas.addEventListener('dragover',  e => e.preventDefault());
    canvas.addEventListener('drop',      onDrop);

    document.getElementById('fp-fit')?.addEventListener('click', fitView);
    document.getElementById('fp-zoom-in')?.addEventListener('click',
      () => zoomAt(canvas.width / 2, canvas.height / 2, 1.25));
    document.getElementById('fp-zoom-out')?.addEventListener('click',
      () => zoomAt(canvas.width / 2, canvas.height / 2, 0.8));
    document.getElementById('fp-export-png')?.addEventListener('click', exportPNG);
    document.getElementById('fp-generate')?.addEventListener('click', onGenerate);
    document.getElementById('fp-mode-2d')?.addEventListener('click', () => setViewMode('2d'));
    document.getElementById('fp-mode-3d')?.addEventListener('click', () => setViewMode('3d'));

    loadPlan(DEMO);
  }

  // ─── Public API ──────────────────────────────────────────────────────────────
  function resize() {
    if (!canvas) return;
    const w = canvas.offsetWidth, h = canvas.offsetHeight;
    if (!w || !h || (canvas.width === w && canvas.height === h)) return;
    canvas.width = w;
    canvas.height = h;
    if (plan) fitView(); else draw();
  }

  function loadPlan(p) {
    plan = p;
    if (viewMode === '3d' && three) {
      // Rebuild 3D scene with new plan
      const { scene, camera, controls } = three;
      while (scene.children.length > 0) scene.remove(scene.children[0]);
      // Re-add lights
      scene.add(new window.THREE.AmbientLight(0xfff8f0, 0.7));
      const sun = new window.THREE.DirectionalLight(0xfff5e0, 1.8);
      sun.position.set(5, 10, 5); sun.castShadow = true; scene.add(sun);
      scene.add(new window.THREE.DirectionalLight(0xc8d8ff, 0.4));
      populateScene(scene, p, camera, controls);
      controls.update();
    } else {
      requestAnimationFrame(() => { resize(); fitView(); });
    }
  }

  function fitView() {
    if (!plan || !canvas || !canvas.width) return;
    const pad = 56;
    const sx = (canvas.width  - pad * 2) / plan.width;
    const sy = (canvas.height - pad * 2) / plan.height;
    tscale = Math.min(sx, sy);
    tx = (canvas.width  - plan.width  * tscale) / 2;
    ty = (canvas.height - plan.height * tscale) / 2;
    draw();
  }

  // ─── Zoom / Pan ──────────────────────────────────────────────────────────────
  function zoomAt(cx, cy, factor) {
    tx = cx + (tx - cx) * factor;
    ty = cy + (ty - cy) * factor;
    tscale *= factor;
    draw();
  }

  function onWheel(e) {
    e.preventDefault();
    const r = canvas.getBoundingClientRect();
    zoomAt(e.clientX - r.left, e.clientY - r.top, e.deltaY < 0 ? 1.1 : 1 / 1.1);
  }

  function onMouseDown(e) {
    panning = true;
    panStart = [e.clientX - tx, e.clientY - ty];
    canvas.style.cursor = 'grabbing';
  }
  function onMouseMove(e) {
    if (!panning) return;
    tx = e.clientX - panStart[0];
    ty = e.clientY - panStart[1];
    draw();
  }
  function onMouseUp() { panning = false; canvas.style.cursor = 'grab'; }

  // ─── Drop handler ────────────────────────────────────────────────────────────
  function onDrop(e) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;

    if (file.name.endsWith('.json')) {
      const reader = new FileReader();
      reader.onload = ev => {
        try { loadPlan(JSON.parse(ev.target.result)); }
        catch { showToast?.('Invalid floor plan JSON'); }
      };
      reader.readAsText(file);

    } else if (file.name.endsWith('.ply')) {
      _pendingPlyFile = file;
      // Show the demo still but with a ready indicator
      drawPlyReady(file.name);
      showToast?.('PLY loaded — click "Generate from PLY" to extract floor plan');

    } else {
      showToast?.('Drop a .ply scan or a .json floor plan');
    }
  }

  function drawPlyReady(name) {
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#f7f6f4';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const cx = canvas.width / 2, cy = canvas.height / 2;
    ctx.fillStyle = '#1a1916';
    ctx.font = '500 15px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(name, cx, cy - 12);
    ctx.font = '13px "DM Sans", sans-serif';
    ctx.fillStyle = '#8a877f';
    ctx.fillText('Click "Generate from PLY" to extract the floor plan', cx, cy + 14);
  }

  // ─── Generate (calls SpatialLM backend) ──────────────────────────────────────
  async function onGenerate() {
    if (generating) return;

    const hasPly = _pendingPlyFile || window._plyUrl;
    if (!hasPly) {
      showToast?.('Drop a .ply file here, or run a scan first');
      return;
    }

    generating = true;
    const btn = document.getElementById('fp-generate');
    if (btn) { btn.textContent = 'Generating…'; btn.disabled = true; }
    drawGenerating();

    try {
      let body;
      if (_pendingPlyFile) {
        const b64 = await fileToBase64(_pendingPlyFile);
        body = { ply_base64: b64 };
      } else {
        body = { ply_url: window._plyUrl };
      }

      // Submit job
      const submitRes = await fetch(`${API_BASE}/floorplan/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!submitRes.ok) throw new Error(`Submit failed: ${submitRes.status}`);
      const { id: jobId } = await submitRes.json();

      // Poll
      const start = Date.now();
      while (true) {
        await sleep(4000);
        const statusRes = await fetch(`${API_BASE}/floorplan/status/${jobId}`);
        const status = await statusRes.json();
        const elapsed = Math.round((Date.now() - start) / 1000);
        drawGenerating(elapsed);

        if (status.status === 'COMPLETED') {
          const fp = spatialLMToFloorPlan(status.output);
          loadPlan(fp);
          showToast?.('Floor plan ready');
          break;
        } else if (status.status === 'FAILED') {
          throw new Error('Job failed: ' + JSON.stringify(status.error || status));
        }
        // IN_QUEUE / IN_PROGRESS — keep polling
      }

    } catch (err) {
      showToast?.('Error: ' + err.message);
      console.error('[FP]', err);
      // Restore demo on failure
      loadPlan(DEMO);
    } finally {
      generating = false;
      if (btn) { btn.textContent = 'Generate from PLY'; btn.disabled = false; }
    }
  }

  function drawGenerating(elapsed) {
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#f7f6f4';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const cx = canvas.width / 2, cy = canvas.height / 2;
    const t = Date.now() / 1000;
    const r = 18;

    // Spinner
    ctx.strokeStyle = '#d4d0c8';
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.arc(cx, cy - 32, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.strokeStyle = '#1a1916';
    ctx.beginPath();
    ctx.arc(cx, cy - 32, r, t * 3, t * 3 + Math.PI * 0.7);
    ctx.stroke();

    ctx.fillStyle = '#1a1916';
    ctx.font = '500 14px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText('Extracting floor plan with SpatialLM…', cx, cy + 2);

    if (elapsed) {
      ctx.fillStyle = '#8a877f';
      ctx.font = '12px "DM Sans", sans-serif';
      ctx.fillText(`${elapsed}s elapsed`, cx, cy + 24);
    }
  }

  // ─── SpatialLM JSON → floor plan format ─────────────────────────────────────
  // SpatialLM returns coordinates in meters; convert to cm (scale=100)
  function spatialLMToFloorPlan(data) {
    console.log('[FP] SpatialLM raw output:', JSON.stringify(data).slice(0, 500));
    const b   = data.bounds;
    const S   = 100;        // cm per meter
    const pad = 60;         // cm padding

    const tx2 = x => (x - b.min_x) * S + pad;
    const ty2 = y => (y - b.min_y) * S + pad;

    return {
      width:  b.width  * S + pad * 2,
      height: b.height * S + pad * 2,
      scale:  100,
      rooms:  [],           // SpatialLM doesn't output room polygons
      walls:  data.walls.map(w => [
        [tx2(w.start[0]), ty2(w.start[1])],
        [tx2(w.end[0]),   ty2(w.end[1])],
      ]),
      doors: data.doors.map(d => ({
        hinge: [tx2(d.position[0]), ty2(d.position[1])],
        len:   d.width * S,
        dir:   d.wall_dir,
      })),
      windows: (data.windows || []).map(win => ({
        center: [tx2(win.position[0]), ty2(win.position[1])],
        width:  win.width * S,
      })),
      objects: (data.objects || []).map(o => ({
        label:  o.class,
        center: [tx2(o.center[0]), ty2(o.center[1])],
        rot:    o.rotation,
        scale:  o.scale ? [o.scale[0] * S, o.scale[1] * S] : [40, 40],
      })),
    };
  }

  // ─── Export ──────────────────────────────────────────────────────────────────
  function exportPNG() {
    const a = document.createElement('a');
    a.download = 'floor-plan.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }

  // ─── Draw ────────────────────────────────────────────────────────────────────
  function draw() {
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#f7f6f4';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (!plan) { drawPlaceholder(); return; }

    ctx.save();
    ctx.translate(tx, ty);
    ctx.scale(tscale, tscale);

    drawRooms();
    drawWalls();
    drawWindows();
    drawDoors();
    drawObjects();
    drawLabels();
    if (plan.rooms?.length) drawDimensions();

    ctx.restore();
    drawScaleBar();
    drawNorthArrow();
  }

  function drawPlaceholder() {
    ctx.fillStyle = '#8a877f';
    ctx.font = '14px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Drop a .ply scan or a .json floor plan', canvas.width / 2, canvas.height / 2);
  }

  function drawRooms() {
    (plan.rooms || []).forEach(r => {
      ctx.beginPath();
      ctx.moveTo(r.poly[0][0], r.poly[0][1]);
      r.poly.slice(1).forEach(p => ctx.lineTo(p[0], p[1]));
      ctx.closePath();
      ctx.fillStyle = r.color;
      ctx.fill();
    });
  }

  function drawWalls() {
    ctx.strokeStyle = '#2a2825';
    ctx.lineCap = 'square';
    ctx.lineJoin = 'miter';
    ctx.lineWidth = 7;
    (plan.walls || []).forEach(w => {
      ctx.beginPath();
      ctx.moveTo(w[0][0], w[0][1]);
      ctx.lineTo(w[1][0], w[1][1]);
      ctx.stroke();
    });
  }

  function drawWindows() {
    // Drawn as triple lines across the wall
    (plan.windows || []).forEach(win => {
      const cx = win.center[0], cy = win.center[1];
      const hw = win.width / 2;

      ctx.strokeStyle = '#2a2825';
      ctx.lineWidth = 1.5;
      for (let d = -1; d <= 1; d++) {
        ctx.beginPath();
        ctx.moveTo(cx - hw, cy + d * 3);
        ctx.lineTo(cx + hw, cy + d * 3);
        ctx.stroke();
      }
    });
  }

  function drawDoors() {
    ctx.strokeStyle = '#2a2825';
    ctx.lineWidth = 1.5;

    (plan.doors || []).forEach(d => {
      const [hx, hy] = d.hinge;
      const ex = hx + Math.cos(d.dir) * d.len;
      const ey = hy + Math.sin(d.dir) * d.len;

      // Door leaf (open position)
      ctx.beginPath();
      ctx.moveTo(hx, hy);
      ctx.lineTo(ex, ey);
      ctx.stroke();

      // Swing arc
      ctx.beginPath();
      ctx.arc(hx, hy, d.len, d.dir - Math.PI / 2, d.dir, false);
      ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    });
  }

  function drawObjects() {
    (plan.objects || []).forEach(o => {
      const [cx, cy] = o.center;
      const [sw, sh]  = o.scale || [40, 40];
      const hw = sw / 2, hh = sh / 2;
      const label = (o.label || '').toLowerCase();
      const key   = Object.keys(OBJ_TYPES).find(k => label.includes(k));
      const type  = OBJ_TYPES[key];
      const isCylinder = type?.shape === 'cylinder';

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(o.rot || 0);

      ctx.strokeStyle = '#8a877f';
      ctx.lineWidth = 1;
      ctx.fillStyle = 'rgba(200,195,185,0.3)';
      ctx.beginPath();
      if (isCylinder) {
        ctx.arc(0, 0, Math.min(hw, hh), 0, Math.PI * 2);
      } else {
        ctx.rect(-hw, -hh, sw, sh);
      }
      ctx.fill();
      ctx.stroke();

      ctx.fillStyle = '#8a877f';
      ctx.font = '9px "DM Sans", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(o.label || '', 0, 0);

      ctx.restore();
    });
  }

  function drawLabels() {
    (plan.rooms || []).forEach(r => {
      if (!r.label) return;
      const xs = r.poly.map(p => p[0]);
      const ys = r.poly.map(p => p[1]);
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
      const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      const rw = Math.max(...xs) - Math.min(...xs);
      const fs = Math.max(10, Math.min(16, rw * 0.075));

      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillStyle = '#1a1916';
      ctx.font = `500 ${fs}px "DM Sans", sans-serif`;
      ctx.fillText(r.label, cx, cy - fs * 0.55);

      if (r.area) {
        ctx.font = `${fs * 0.82}px "DM Sans", sans-serif`;
        ctx.fillStyle = '#8a877f';
        ctx.fillText(`${r.area} m²`, cx, cy + fs * 0.65);
      }
    });
  }

  function drawDimensions() {
    const dim = 28, tick = 6;
    const W = plan.width, H = plan.height;
    const mW = (W / plan.scale).toFixed(1);
    const mH = (H / plan.scale).toFixed(1);

    ctx.strokeStyle = '#b0aba0';
    ctx.fillStyle   = '#8a877f';
    ctx.lineWidth   = 0.8;
    ctx.font = '11px "DM Sans", sans-serif';
    ctx.setLineDash([2, 3]);

    // Bottom (width)
    ctx.beginPath(); ctx.moveTo(0, H + dim); ctx.lineTo(W, H + dim); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(0, H + dim - tick); ctx.lineTo(0, H + dim + tick);
    ctx.moveTo(W, H + dim - tick); ctx.lineTo(W, H + dim + tick);
    ctx.stroke();
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(`${mW} m`, W / 2, H + dim + 4);

    // Right (height)
    ctx.setLineDash([2, 3]);
    ctx.beginPath(); ctx.moveTo(W + dim, 0); ctx.lineTo(W + dim, H); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(W + dim - tick, 0); ctx.lineTo(W + dim + tick, 0);
    ctx.moveTo(W + dim - tick, H); ctx.lineTo(W + dim + tick, H);
    ctx.stroke();
    ctx.save();
    ctx.translate(W + dim + 14, H / 2);
    ctx.rotate(Math.PI / 2);
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText(`${mH} m`, 0, 0);
    ctx.restore();
  }

  function drawScaleBar() {
    if (!plan) return;
    const mPx = tscale * plan.scale;
    const bm  = mPx * 5 < 160 ? 5 : mPx * 2 < 160 ? 2 : 1;
    const bPx = bm * mPx;
    const x = 20, y = canvas.height - 20;

    ctx.strokeStyle = '#1a1916'; ctx.lineWidth = 1.5; ctx.lineCap = 'butt';
    ctx.beginPath();
    ctx.moveTo(x, y - 5); ctx.lineTo(x, y);
    ctx.lineTo(x + bPx, y); ctx.lineTo(x + bPx, y - 5);
    ctx.stroke();
    ctx.fillStyle = '#1a1916';
    ctx.font = '10px "DM Sans", sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText(`${bm} m`, x + bPx / 2, y - 6);
  }

  function drawNorthArrow() {
    const x = canvas.width - 24, y = canvas.height - 30;
    ctx.fillStyle = '#1a1916';
    ctx.beginPath();
    ctx.moveTo(x, y - 14);
    ctx.lineTo(x - 5, y + 6);
    ctx.lineTo(x, y + 1);
    ctx.lineTo(x + 5, y + 6);
    ctx.closePath();
    ctx.fill();
    ctx.font = 'bold 9px "DM Sans", sans-serif';
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText('N', x, y - 16);
  }

  // ─── Utilities ───────────────────────────────────────────────────────────────
  function fileToBase64(file) {
    return new Promise((resolve, reject) => {
      const r = new FileReader();
      r.onload  = () => resolve(r.result.split(',')[1]);
      r.onerror = reject;
      r.readAsDataURL(file);
    });
  }

  function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

  // ─── 2D / 3D mode toggle ─────────────────────────────────────────────────────
  function setViewMode(mode) {
    viewMode = mode;
    const c2d = document.getElementById('fp-canvas');
    const c3d = document.getElementById('fp-3d-container');
    const btn2 = document.getElementById('fp-mode-2d');
    const btn3 = document.getElementById('fp-mode-3d');

    btn2?.classList.toggle('active', mode === '2d');
    btn3?.classList.toggle('active', mode === '3d');

    if (mode === '2d') {
      c2d.style.display = 'block';
      c3d.style.display = 'none';
      destroy3D();
      resize();
    } else {
      c2d.style.display = 'none';
      c3d.style.display = 'flex';
      requestAnimationFrame(() => init3D());
    }
  }

  // ─── Three.js 3D renderer ─────────────────────────────────────────────────────
  const THREE_CDN  = 'https://cdn.jsdelivr.net/npm/three@0.132.0/build/three.min.js';
  const ORBIT_CDN  = 'https://cdn.jsdelivr.net/npm/three@0.132.0/examples/js/controls/OrbitControls.js';

  function loadScript(src, cb) {
    if (document.querySelector(`script[src="${src}"]`)) { cb(); return; }
    const s = document.createElement('script');
    s.src = src; s.onload = cb; document.head.appendChild(s);
  }

  function init3D() {
    const container = document.getElementById('fp-3d-container');
    if (!container) return;

    if (!window.THREE) {
      loadScript(THREE_CDN, () => loadScript(ORBIT_CDN, () => build3D(container)));
    } else if (!window.THREE.OrbitControls) {
      loadScript(ORBIT_CDN, () => build3D(container));
    } else {
      build3D(container);
    }
  }

  // Object type → { height(m), color, shape? }
  // shape: 'box' (default) | 'cylinder'
  const OBJ_TYPES = {
    // Seating
    sofa:         { h: 0.85, color: 0x8b7355 },
    couch:        { h: 0.85, color: 0x8b7355 },
    sectional:    { h: 0.85, color: 0x8b7355 },
    loveseat:     { h: 0.85, color: 0x9b8060 },
    chair:        { h: 0.90, color: 0xa0785a },
    armchair:     { h: 0.90, color: 0xa0785a },
    recliner:     { h: 0.95, color: 0x906848 },
    ottoman:      { h: 0.45, color: 0xb09070 },
    stool:        { h: 0.75, color: 0xc0a880 },
    bench:        { h: 0.50, color: 0xb8a070 },
    // Sleep
    bed:          { h: 0.55, color: 0x9b8ea0 },
    nightstand:   { h: 0.65, color: 0xc0a882 },
    dresser:      { h: 1.20, color: 0xb09870 },
    // Tables & desks
    desk:         { h: 0.76, color: 0xc4a882 },
    table:        { h: 0.76, color: 0xc4a882 },
    dining:       { h: 0.76, color: 0xd0b890 },
    coffee:       { h: 0.45, color: 0xb89860 },
    side:         { h: 0.60, color: 0xc0a870 },
    console:      { h: 0.80, color: 0xb8a070 },
    // Storage
    cabinet:      { h: 1.20, color: 0xb0a090 },
    wardrobe:     { h: 1.90, color: 0xa89880 },
    shelf:        { h: 1.60, color: 0xb8a888 },
    bookcase:     { h: 1.80, color: 0xb8a888 },
    bookshelf:    { h: 1.80, color: 0xb8a888 },
    chest:        { h: 0.80, color: 0xb09070 },
    credenza:     { h: 0.85, color: 0xb09870 },
    // Lighting — cylinder shape
    lamp:         { h: 1.50, color: 0xf0e0a0, shape: 'cylinder' },
    floor_lamp:   { h: 1.60, color: 0xf0e0a0, shape: 'cylinder' },
    table_lamp:   { h: 0.55, color: 0xf0e0a0, shape: 'cylinder' },
    light:        { h: 1.50, color: 0xf0e0a0, shape: 'cylinder' },
    chandelier:   { h: 0.60, color: 0xf5e898, shape: 'cylinder' },
    // AV & tech
    tv:           { h: 1.10, color: 0x303030 },
    television:   { h: 1.10, color: 0x303030 },
    monitor:      { h: 1.00, color: 0x303030 },
    speaker:      { h: 0.90, color: 0x404040 },
    // Kitchen
    refrigerator: { h: 1.75, color: 0xd0d0d0 },
    fridge:       { h: 1.75, color: 0xd0d0d0 },
    stove:        { h: 0.90, color: 0x606060 },
    oven:         { h: 0.90, color: 0x606060 },
    microwave:    { h: 1.40, color: 0x707070 },
    dishwasher:   { h: 0.90, color: 0xd0d0d0 },
    counter:      { h: 0.90, color: 0xd8c8a8 },
    island:       { h: 0.90, color: 0xd8c8a8 },
    // Bathroom
    toilet:       { h: 0.40, color: 0xe8e8e8 },
    bathtub:      { h: 0.55, color: 0xd0d8e0 },
    sink:         { h: 0.85, color: 0xd8dce0 },
    shower:       { h: 0.10, color: 0xc8d8e8 },
    vanity:       { h: 0.85, color: 0xd0ccc0 },
    // Decor & misc
    plant:        { h: 1.20, color: 0x5a8a50, shape: 'cylinder' },
    mirror:       { h: 1.60, color: 0xd0e8f0 },
    piano:        { h: 1.20, color: 0x202020 },
    fireplace:    { h: 1.10, color: 0x706050 },
    curtain:      { h: 2.20, color: 0xd8c8b0 },
    rug:          { h: 0.02, color: 0xc08060 },
  };

  function makeFloorTexture(THREE) {
    const size = 512;
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#e8e0d0';
    ctx.fillRect(0, 0, size, size);
    const plankW = size / 4, plankH = size / 12;
    ctx.fillStyle = '#d4c8b0';
    for (let row = 0; row < size / plankH; row++) {
      const offset = (row % 2) * (plankW / 2);
      for (let col = -1; col < size / plankW + 1; col++) {
        const x = col * plankW + offset, y = row * plankH;
        ctx.strokeStyle = '#c8bc9e';
        ctx.lineWidth = 1.5;
        ctx.strokeRect(x + 1, y + 1, plankW - 2, plankH - 2);
        ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.03})`;
        ctx.fillRect(x + 1, y + 1, plankW - 2, plankH - 2);
      }
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    return tex;
  }

  function makeWallTexture(THREE) {
    const size = 256;
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#f4f0e8';
    ctx.fillRect(0, 0, size, size);
    for (let i = 0; i < 400; i++) {
      ctx.fillStyle = `rgba(0,0,0,${Math.random() * 0.015})`;
      ctx.fillRect(Math.random() * size, Math.random() * size, Math.random() * 6 + 1, Math.random() * 6 + 1);
    }
    const tex = new THREE.CanvasTexture(c);
    tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
    return tex;
  }

  function build3D(container) {
    destroy3D();
    if (!window.THREE) return;
    const THREE = window.THREE;
    const w = container.clientWidth  || 800;
    const h = container.clientHeight || 600;

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(w, h);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.outputEncoding = THREE.sRGBEncoding || 3001;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.1;
    renderer.setClearColor(0x1a1916);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x2a2825);
    scene.fog = new THREE.FogExp2(0x2a2825, 0.06);

    const camera = new THREE.PerspectiveCamera(55, w / h, 0.01, 100);
    const controls = new THREE.OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minPolarAngle = 0.1;
    controls.maxPolarAngle = Math.PI / 2.1;
    controls.minDistance = 1;
    controls.maxDistance = 30;

    // Lighting
    scene.add(new THREE.AmbientLight(0xfff5e8, 0.5));
    const hemi = new THREE.HemisphereLight(0xfff8f0, 0x8090a0, 0.4);
    scene.add(hemi);
    const sun = new THREE.DirectionalLight(0xfff8f0, 1.5);
    sun.position.set(8, 12, 6);
    sun.castShadow = true;
    sun.shadow.mapSize.width = 2048;
    sun.shadow.mapSize.height = 2048;
    sun.shadow.camera.near = 0.1;
    sun.shadow.camera.far = 50;
    sun.shadow.camera.left = -15;
    sun.shadow.camera.right = 15;
    sun.shadow.camera.top = 15;
    sun.shadow.camera.bottom = -15;
    sun.shadow.bias = -0.001;
    scene.add(sun);
    const fill = new THREE.DirectionalLight(0xc8d8ff, 0.3);
    fill.position.set(-6, 4, -4);
    scene.add(fill);

    if (plan) {
      populateScene(scene, plan, camera, controls, THREE);
    } else {
      scene.add(new THREE.GridHelper(10, 20, 0x444440, 0x2a2825));
      camera.position.set(0, 6, 8);
      controls.target.set(0, 0, 0);
    }
    controls.update();

    let animId;
    function animate() {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    }
    animate();

    function onResize() {
      const cw = container.clientWidth, ch = container.clientHeight;
      if (!cw || !ch) return;
      camera.aspect = cw / ch;
      camera.updateProjectionMatrix();
      renderer.setSize(cw, ch);
    }
    window.addEventListener('resize', onResize);

    three = { renderer, scene, camera, controls, animId, onResize };
  }

  function populateScene(scene, p, camera, controls, THREE) {
    if (!THREE) THREE = window.THREE;
    const S      = p.scale || 100;
    const WALL_H = 2.6;
    const WALL_T = 0.12;
    const W = p.width  / S;
    const H = p.height / S;
    const cx = W / 2, cz = H / 2;

    const floorTex = makeFloorTexture(THREE);
    floorTex.repeat.set(W * 0.8, H * 0.8);
    const wallTex  = makeWallTexture(THREE);

    const floorMat = new THREE.MeshStandardMaterial({ map: floorTex, roughness: 0.85, metalness: 0.0 });
    const wallMat  = new THREE.MeshStandardMaterial({ map: wallTex,  roughness: 0.9,  metalness: 0.0, color: 0xf0ece4 });
    const ceilMat  = new THREE.MeshStandardMaterial({ color: 0xfafaf8, roughness: 1.0 });

    // Floor
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(W + 0.5, H + 0.5), floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(cx, 0, -cz);
    floor.receiveShadow = true;
    scene.add(floor);

    // Ceiling (semi-transparent)
    const ceil = new THREE.Mesh(new THREE.PlaneGeometry(W, H), ceilMat);
    ceil.rotation.x = Math.PI / 2;
    ceil.position.set(cx, WALL_H, -cz);
    scene.add(ceil);

    // Walls
    (p.walls || []).forEach(wall => {
      const [x1, y1] = wall[0];
      const [x2, y2] = wall[1];
      const dx = (x2 - x1) / S, dz = (y2 - y1) / S;
      const len = Math.sqrt(dx * dx + dz * dz);
      if (len < 0.05) return;
      const geo  = new THREE.BoxGeometry(len, WALL_H, WALL_T);
      const mesh = new THREE.Mesh(geo, wallMat);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.position.set((x1 + x2) / (2 * S), WALL_H / 2, -(y1 + y2) / (2 * S));
      mesh.rotation.y = -Math.atan2(dz, dx);
      scene.add(mesh);
    });

    // Objects / furniture
    (p.objects || []).forEach(o => {
      const label = (o.label || '').toLowerCase();
      const key   = Object.keys(OBJ_TYPES).find(k => label.includes(k));
      const type  = OBJ_TYPES[key] || { h: 0.5, color: 0xc8b99a, shape: 'box' };
      const [ox, oy] = o.center;
      const [sw, sd] = o.scale ? [Math.max(o.scale[0]/S, 0.2), Math.max(o.scale[1]/S, 0.2)] : [0.6, 0.6];
      const sh = type.h;

      const mat = new THREE.MeshStandardMaterial({ color: type.color, roughness: 0.8, metalness: 0.05 });
      let geo;
      if (type.shape === 'cylinder') {
        const r = Math.min(sw, sd) / 2;
        geo = new THREE.CylinderGeometry(r, r, sh, 16);
      } else {
        geo = new THREE.BoxGeometry(sw, sh, sd);
      }
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(ox / S, sh / 2, -oy / S);
      mesh.rotation.y = -(o.rot || 0);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      scene.add(mesh);

      // Label sprite
      const sprite = makeLabel(THREE, o.label || key || 'object');
      sprite.position.set(ox / S, sh + 0.25, -oy / S);
      scene.add(sprite);
    });

    // Door arcs
    (p.doors || []).forEach(d => {
      const geo = new THREE.BoxGeometry(d.len / S || 0.9, WALL_H * 0.9, 0.04);
      const mat = new THREE.MeshStandardMaterial({ color: 0xc8a878, roughness: 0.6 });
      const mesh = new THREE.Mesh(geo, mat);
      const [hx, hy] = d.hinge;
      mesh.position.set(hx / S, WALL_H * 0.45, -hy / S);
      mesh.rotation.y = -(d.dir || 0);
      scene.add(mesh);
    });

    // Point light inside room
    const roomLight = new THREE.PointLight(0xfff5e0, 0.8, Math.max(W, H) * 2);
    roomLight.position.set(cx, WALL_H - 0.3, -cz);
    scene.add(roomLight);

    camera.position.set(cx, Math.max(W, H) * 0.85, cz * 1.4);
    controls.target.set(cx, 0.8, -cz);
  }

  function makeLabel(THREE, text) {
    const canvas = document.createElement('canvas');
    canvas.width = 256; canvas.height = 64;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(0,0,0,0.6)';
    ctx.roundRect ? ctx.roundRect(4, 4, 248, 56, 8) : ctx.fillRect(4, 4, 248, 56);
    ctx.fill();
    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 28px sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, 128, 32);
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({ map: tex, transparent: true, depthTest: false });
    const sprite = new THREE.Sprite(mat);
    sprite.scale.set(0.9, 0.22, 1);
    return sprite;
  }

  function destroy3D() {
    if (!three) return;
    cancelAnimationFrame(three.animId);
    window.removeEventListener('resize', three.onResize);
    three.renderer.dispose();
    const container = document.getElementById('fp-3d-container');
    if (container && three.renderer.domElement.parentNode === container) {
      container.removeChild(three.renderer.domElement);
    }
    three = null;
  }

  // ─── Boot ────────────────────────────────────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  function autoGenerate(file) {
    _pendingPlyFile = file;
    // Switch to 3D mode automatically for a scan
    setViewMode('3d');
    requestAnimationFrame(() => onGenerate());
  }

  window.fpViewer = { loadPlan, fitView, resize, autoGenerate };
})();
