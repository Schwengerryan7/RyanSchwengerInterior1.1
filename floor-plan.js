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

  // ── Edit mode state ───────────────────────────────────────────────────────────
  let editMode = false;
  let selectedIdx = -1;   // index into plan.objects, -1 = none
  let dragState = null;   // null or {type:'move'|'resize', edge, startPX, startPY, origCenter, origScale}

  // Convert canvas pixel coords → plan coords
  function canvasToPlan(cx, cy) {
    return [(cx - tx) / tscale, (cy - ty) / tscale];
  }

  // Hit-test: which object index is at plan coords (planX, planY)?
  function hitTestObjects(planX, planY) {
    if (!plan?.objects) return -1;
    for (let i = plan.objects.length - 1; i >= 0; i--) {
      const o = plan.objects[i];
      const [cx, cy] = o.center;
      const [sw, sh] = o.scale || [40, 40];
      if (planX >= cx-sw/2-10 && planX <= cx+sw/2+10 &&
          planY >= cy-sh/2-10 && planY <= cy+sh/2+10) return i;
    }
    return -1;
  }

  // Which resize edge is the cursor near (or null for move)?
  function getResizeEdge(planX, planY, o) {
    const [cx, cy] = o.center;
    const [sw, sh] = o.scale || [40, 40];
    const t = 12;
    if (Math.abs(planX-(cx+sw/2)) < t && planY > cy-sh/2 && planY < cy+sh/2) return 'right';
    if (Math.abs(planX-(cx-sw/2)) < t && planY > cy-sh/2 && planY < cy+sh/2) return 'left';
    if (Math.abs(planY-(cy+sh/2)) < t && planX > cx-sw/2 && planX < cx+sw/2) return 'bottom';
    if (Math.abs(planY-(cy-sh/2)) < t && planX > cx-sw/2 && planX < cx+sw/2) return 'top';
    return null;
  }

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
    document.getElementById('fp-load-latest')?.addEventListener('click', loadLatest);
    document.getElementById('fp-export-png')?.addEventListener('click', exportPNG);
    document.getElementById('fp-export-json')?.addEventListener('click', exportJSON);
    document.getElementById('fp-generate')?.addEventListener('click', onGenerate);
    document.getElementById('fp-mode-2d')?.addEventListener('click', () => setViewMode('2d'));
    document.getElementById('fp-mode-3d')?.addEventListener('click', () => setViewMode('3d'));

    document.getElementById('fp-edit')?.addEventListener('click', () => setEditMode(!editMode));
    document.getElementById('fp-edit-delete')?.addEventListener('click', () => {
      if (selectedIdx >= 0 && plan?.objects) {
        plan.objects.splice(selectedIdx, 1);
        selectedIdx = -1;
        draw();
      }
    });
    document.getElementById('fp-edit-save')?.addEventListener('click', saveEdits);

    document.addEventListener('keydown', e => {
      if (!editMode || selectedIdx < 0) return;
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (document.activeElement === document.body || document.activeElement === canvas) {
          plan.objects.splice(selectedIdx, 1);
          selectedIdx = -1; draw();
        }
      }
      if (e.key === 'Escape') { selectedIdx = -1; draw(); }
    });

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
    if (editMode) {
      const r = canvas.getBoundingClientRect();
      const [planX, planY] = canvasToPlan(e.clientX - r.left, e.clientY - r.top);
      const hitIdx = hitTestObjects(planX, planY);
      if (hitIdx >= 0) {
        selectedIdx = hitIdx;
        const o = plan.objects[hitIdx];
        const edge = getResizeEdge(planX, planY, o);
        dragState = { type: edge ? 'resize' : 'move', edge,
                      startPX: planX, startPY: planY,
                      origCenter: [...o.center], origScale: [...(o.scale||[40,40])] };
        draw();
        return;
      }
      selectedIdx = -1; draw(); return;
    }
    panning = true;
    panStart = [e.clientX - tx, e.clientY - ty];
    canvas.style.cursor = 'grabbing';
  }
  function onMouseMove(e) {
    if (editMode && dragState && selectedIdx >= 0) {
      const r = canvas.getBoundingClientRect();
      const [planX, planY] = canvasToPlan(e.clientX - r.left, e.clientY - r.top);
      const dx = planX - dragState.startPX, dy = planY - dragState.startPY;
      const o = plan.objects[selectedIdx];
      if (dragState.type === 'move') {
        o.center = [dragState.origCenter[0]+dx, dragState.origCenter[1]+dy];
      } else {
        const [ow, oh] = dragState.origScale;
        const edge = dragState.edge;
        if (edge==='right')  { o.scale=[Math.max(20,ow+dx), oh]; }
        if (edge==='left')   { o.scale=[Math.max(20,ow-dx), oh]; o.center[0]=dragState.origCenter[0]+dx/2; }
        if (edge==='bottom') { o.scale=[ow, Math.max(20,oh+dy)]; }
        if (edge==='top')    { o.scale=[ow, Math.max(20,oh-dy)]; o.center[1]=dragState.origCenter[1]+dy/2; }
      }
      draw(); return;
    }
    if (!panning) return;
    tx = e.clientX - panStart[0];
    ty = e.clientY - panStart[1];
    draw();
  }
  function onMouseUp() {
    dragState = null;
    if (editMode) return;
    panning = false;
    canvas.style.cursor = 'grab';
  }

  // ─── Drop handler ────────────────────────────────────────────────────────────
  function onDrop(e) {
    e.preventDefault();
    const file = e.dataTransfer.files[0];
    if (!file) return;

    if (file.name.endsWith('.json')) {
      const reader = new FileReader();
      reader.onload = ev => {
        try {
          const parsed = JSON.parse(ev.target.result);
          // Raw backend JSON has `bounds` + `walls` as objects with start/end.
          // Converted plan JSON has `width` at the top level.
          const data = parsed.bounds ? spatialLMToFloorPlan(parsed) : parsed;
          loadPlan(data);
        }
        catch (e) { console.error(e); showToast?.('Invalid floor plan JSON'); }
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
      // Include Grounding DINO detections from scan stage
      if (window._scanDetectedObjects?.length) {
        body.detected_objects = window._scanDetectedObjects;
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
    ctx.fillText('Generating floor plan…', cx, cy + 2);

    if (elapsed) {
      ctx.fillStyle = '#8a877f';
      ctx.font = '12px "DM Sans", sans-serif';
      ctx.fillText(`${elapsed}s elapsed`, cx, cy + 24);
    }
  }

  // ─── Planar face extraction: walls → room polygons ───────────────────────────
  // Builds a half-edge graph from wall segments, traverses all faces using the
  // DCEL "next CW neighbor of reverse edge" rule, filters the outer face, then
  // classifies each interior face by the furniture objects it contains.

  function pointInPolygon(px, py, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const xi = poly[i][0], yi = poly[i][1];
      const xj = poly[j][0], yj = poly[j][1];
      if ((yi > py) !== (yj > py) && px < ((xj - xi) * (py - yi)) / (yj - yi) + xi)
        inside = !inside;
    }
    return inside;
  }

  function extractRoomsFromWalls(walls, objects) {
    if (!walls || walls.length < 3) return [];

    const SNAP = 10; // cm — tolerance for merging nearby wall endpoints

    // 1. Collect vertices with snapping
    const pts = [];
    function addPt(x, y) {
      for (let i = 0; i < pts.length; i++) {
        if (Math.hypot(pts[i][0] - x, pts[i][1] - y) < SNAP) return i;
      }
      pts.push([x, y]);
      return pts.length - 1;
    }

    // 2. Build directed half-edges (each wall → forward + backward)
    const he = []; // [from, to]
    for (const w of walls) {
      const a = addPt(w[0][0], w[0][1]);
      const b = addPt(w[1][0], w[1][1]);
      if (a === b) continue;
      he.push([a, b]);
      he.push([b, a]);
    }
    if (he.length < 6) return [];

    // 3. Adjacency: outgoing[v] = [{to, edgeIdx, angle}] sorted ascending (CCW)
    const out = Array.from({ length: pts.length }, () => []);
    for (let i = 0; i < he.length; i++) {
      const [from, to] = he[i];
      const angle = Math.atan2(pts[to][1] - pts[from][1], pts[to][0] - pts[from][0]);
      out[from].push({ to, edgeIdx: i, angle });
    }
    for (const list of out) list.sort((a, b) => a.angle - b.angle);

    // 4. For directed edge i (u→v), next edge in face = prev CW neighbor of (v→u)
    function nextInFace(i) {
      const [from, to] = he[i];
      const list = out[to];
      const rev  = list.findIndex(e => e.to === from);
      if (rev === -1) return -1;
      return list[(rev - 1 + list.length) % list.length].edgeIdx;
    }

    // 5. Traverse all faces
    const visited = new Set();
    const faces   = [];

    for (let start = 0; start < he.length; start++) {
      if (visited.has(start)) continue;
      const poly  = [];
      let   e     = start;
      let   guard = he.length + 2;
      while (!visited.has(e) && guard-- > 0) {
        visited.add(e);
        poly.push(pts[he[e][0]]);
        const next = nextInFace(e);
        if (next < 0 || next === start) break;
        e = next;
      }
      if (poly.length < 3) continue;
      let area = 0;
      for (let i = 0; i < poly.length; i++) {
        const j = (i + 1) % poly.length;
        area += poly[i][0] * poly[j][1] - poly[j][0] * poly[i][1];
      }
      faces.push({ poly, area: area / 2 });
    }

    if (!faces.length) return [];

    // 6. Drop the outer face (largest |area|) and tiny noise faces
    const maxAbs = Math.max(...faces.map(f => Math.abs(f.area)));
    const MIN_CM2 = 5000; // ~0.5 m²
    const inner = faces.filter(f => Math.abs(f.area) < maxAbs * 0.95 && Math.abs(f.area) > MIN_CM2);

    // 7. Classify by contained furniture
    // any:  room matches if ANY key is present
    // all:  room matches only if ALL keys are present
    const RULES = [
      { label: 'Master Bedroom', color: '#e8eaf5', mode: 'all', keys: ['bed', 'wardrobe'] },
      { label: 'Bedroom',        color: '#eaeaf5', mode: 'any', keys: ['bed'] },
      { label: 'Bathroom',       color: '#ddf0ec', mode: 'any', keys: ['toilet', 'bathtub', 'shower', 'sink'] },
      { label: 'Kitchen',        color: '#eaf0e8', mode: 'any', keys: ['refrigerator', 'fridge', 'oven', 'stove', 'microwave'] },
      { label: 'Living Room',    color: '#f5f0e8', mode: 'any', keys: ['sofa', 'couch', 'tv', 'television'] },
      { label: 'Dining Room',    color: '#f5ede8', mode: 'any', keys: ['dining table', 'dining_table'] },
      { label: 'Office',         color: '#f0ece4', mode: 'any', keys: ['desk', 'computer', 'monitor'] },
    ];
    const FALLBACK = ['#f5f0e8', '#eaf0e8', '#e8eaf5', '#ddf0ec', '#f5ede8', '#eeece8'];

    // Classify, then promote the largest bedroom to "Master Bedroom" if there are 2+
    let bedroomCount = 0;
    const classified = inner.map((f, idx) => {
      const inside = (objects || []).filter(o => pointInPolygon(o.center[0], o.center[1], f.poly));
      const lbls   = inside.map(o => (o.label || '').toLowerCase());
      let match = null;
      for (const rule of RULES) {
        const hit = rule.mode === 'all'
          ? rule.keys.every(k => lbls.some(l => l.includes(k)))
          : rule.keys.some(k => lbls.some(l => l.includes(k)));
        if (hit) { match = rule; break; }
      }
      if (match?.keys?.includes('bed')) bedroomCount++;
      return {
        label:  match ? match.label : `Room ${idx + 1}`,
        area:   Math.max(1, Math.round(Math.abs(f.area) / 10000)),
        color:  match ? match.color : FALLBACK[idx % FALLBACK.length],
        poly:   f.poly,
        _abs:   Math.abs(f.area),
        _isBed: !!match?.keys?.includes('bed'),
      };
    });

    // With 2+ bedrooms, largest becomes "Master Bedroom", rest "Bedroom"
    if (bedroomCount >= 2) {
      const beds    = classified.filter(r => r._isBed);
      const largest = beds.reduce((a, b) => a._abs > b._abs ? a : b, beds[0]);
      beds.forEach(r => {
        r.label = r === largest ? 'Master Bedroom' : 'Bedroom';
        r.color = r === largest ? '#e8eaf5' : '#eaeaf5';
      });
    }

    return classified.map(({ label, area, color, poly }) => ({ label, area, color, poly }));
  }

  // ─── SpatialLM JSON → floor plan format ─────────────────────────────────────
  function spatialLMToFloorPlan(data) {
    console.log('[FP] SpatialLM raw output:', JSON.stringify(data).slice(0, 500));
    const b   = data.bounds;
    const S   = 100;
    const pad = 60;

    // COLMAP produces arbitrary-scale coordinates. Normalize so the largest
    // room dimension is ≤ 12 m, which keeps 3D rendering sane.
    const rawMax   = Math.max(b.width, b.height);
    const norm     = rawMax > 12 ? 12 / rawMax : 1;   // scale factor (1 if already metric)

    const tx2 = x => (x - b.min_x) * norm * S + pad;
    const ty2 = y => (y - b.min_y) * norm * S + pad;

    const walls = data.walls.map(w => [
      [tx2(w.start[0]), ty2(w.start[1])],
      [tx2(w.end[0]),   ty2(w.end[1])],
    ]);

    const objects = (data.objects || []).map(o => ({
      label:  o.class,
      center: [tx2(o.center[0]), ty2(o.center[1])],
      rot:    o.rotation,
      scale:  o.scale ? [o.scale[0] * S, o.scale[1] * S] : [40, 40],
    }));

    // Prefer rooms from the backend (RoomFormer polygons are precise).
    // Fall back to local DCEL extraction if the backend didn't return them.
    let rooms;
    if (data.rooms && data.rooms.length > 0) {
      const ROOM_COLORS = {
        'Living Room':    '#f5f0e8',
        'Master Bedroom': '#e8eaf5',
        'Bedroom':        '#eaeaf5',
        'Bathroom':       '#ddf0ec',
        'Kitchen':        '#eaf0e8',
        'Dining Room':    '#f5ede8',
        'Office':         '#f0ece4',
      };
      const FALLBACK_COLORS = ['#f5f0e8','#eaf0e8','#e8eaf5','#ddf0ec','#f5ede8','#eeece8'];
      rooms = data.rooms.map((r, i) => ({
        label: r.label,
        area:  r.area,
        color: ROOM_COLORS[r.label] || FALLBACK_COLORS[i % FALLBACK_COLORS.length],
        poly:  r.poly.map(([x, y]) => [tx2(x), ty2(y)]),
      }));
      console.log('[FP] Using', rooms.length, 'rooms from RoomFormer:',
                  rooms.map(r => r.label));
    } else {
      rooms = extractRoomsFromWalls(walls, objects);
      console.log('[FP] RoomFormer returned no rooms; extracted', rooms.length,
                  'rooms from wall graph:', rooms.map(r => r.label));
    }

    return {
      width:  b.width  * norm * S + pad * 2,
      height: b.height * norm * S + pad * 2,
      scale:  100,
      rooms,
      walls,
      doors: (data.doors || []).map(d => {
        const wda = d.wall_dir || 0;
        const halfW = (d.width * S) / 2;
        // Shift from center to hinge (left side along wall direction)
        const hx = tx2(d.position[0]) - Math.cos(wda) * halfW;
        const hy = ty2(d.position[1]) - Math.sin(wda) * halfW;
        return {
          hinge: [hx, hy],
          len:   d.width * S,
          dir:   wda + Math.PI / 2,   // swing perpendicular to wall into room
        };
      }),
      windows: (data.windows || []).map(win => ({
        center: [tx2(win.position[0]), ty2(win.position[1])],
        width:  win.width * S,
      })),
      objects,
    };
  }

  // ─── Load latest saved floor plan from proxy ─────────────────────────────────
  async function loadLatest() {
    try {
      showToast?.('Loading latest floor plan…');
      const res  = await fetch('/floorplan/latest');
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
      const data = await res.json();
      const fp   = data.bounds ? spatialLMToFloorPlan(data) : data;
      loadPlan(fp);
      showToast?.('Floor plan loaded');
    } catch (e) {
      console.error('[FP] loadLatest error:', e);
      showToast?.('Could not load floor plan: ' + e.message);
    }
  }

  // ─── Export ──────────────────────────────────────────────────────────────────
  function exportPNG() {
    const a = document.createElement('a');
    a.download = 'floor-plan.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }

  // Save current plan as floor_plan.json — drop into data/scans/<name>/ for training
  function exportJSON() {
    if (!plan) { showToast?.('No floor plan to save'); return; }
    const blob = new Blob([JSON.stringify(plan, null, 2)], { type: 'application/json' });
    const a    = document.createElement('a');
    a.download = 'floor_plan.json';
    a.href     = URL.createObjectURL(blob);
    a.click();
    showToast?.('floor_plan.json saved — move it to data/scans/<scan_name>/ for training');
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
    // Two-pass: outer glow for depth, then solid dark face
    ctx.lineCap = 'square';
    ctx.lineJoin = 'miter';
    ctx.miterLimit = 10;

    ctx.strokeStyle = 'rgba(0,0,0,0.12)';
    ctx.lineWidth = 16;
    (plan.walls || []).forEach(w => {
      ctx.beginPath();
      ctx.moveTo(w[0][0], w[0][1]);
      ctx.lineTo(w[1][0], w[1][1]);
      ctx.stroke();
    });

    ctx.strokeStyle = '#1a1815';
    ctx.lineWidth = 12;
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
    (plan.doors || []).forEach(d => {
      const [hx, hy] = d.hinge;
      const ex = hx + Math.cos(d.dir) * d.len;
      const ey = hy + Math.sin(d.dir) * d.len;

      ctx.strokeStyle = '#2a2825';
      ctx.lineWidth = 1.5;

      // Door leaf
      ctx.beginPath();
      ctx.moveTo(hx, hy);
      ctx.lineTo(ex, ey);
      ctx.stroke();

      // Swing arc
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.arc(hx, hy, d.len, d.dir - Math.PI / 2, d.dir, false);
      ctx.stroke();
      ctx.setLineDash([]);

      // Label at midpoint of arc
      const labelAngle = d.dir - Math.PI / 4;
      const labelR = d.len * 0.55;
      const lx = hx + Math.cos(labelAngle) * labelR;
      const ly = hy + Math.sin(labelAngle) * labelR;
      ctx.fillStyle = '#5a5750';
      ctx.font = '8px "DM Sans", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('Door', lx, ly);
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

      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(o.rot || 0);

      ctx.strokeStyle = '#8a877f';
      ctx.lineWidth = 1;

      if (type?.shape === 'cylinder' || label.includes('plant') || label.includes('lamp') || label.includes('stool')) {
        // Circular footprint
        ctx.fillStyle = 'rgba(180,200,170,0.35)';
        ctx.beginPath();
        ctx.arc(0, 0, Math.min(hw, hh), 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();

      } else if (label.includes('sofa') || label.includes('couch') || label.includes('sectional')) {
        // Sofa: body + back cushion bar
        ctx.fillStyle = 'rgba(180,160,130,0.45)';
        ctx.strokeStyle = '#7a6a58';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh); ctx.fill(); ctx.stroke();
        ctx.fillStyle = 'rgba(140,120,95,0.6)';
        ctx.fillRect(-hw, hh - sh * 0.28, sw, sh * 0.28);
        // Seat cushion dividers
        ctx.strokeStyle = 'rgba(120,100,80,0.5)';
        const cushions = Math.max(2, Math.round(sw / 60));
        for (let i = 1; i < cushions; i++) {
          const x = -hw + (sw / cushions) * i;
          ctx.beginPath(); ctx.moveTo(x, -hh); ctx.lineTo(x, hh - sh * 0.28); ctx.stroke();
        }

      } else if (label.includes('bed')) {
        // Bed: mattress + headboard + pillows
        ctx.fillStyle = 'rgba(200,190,210,0.45)';
        ctx.strokeStyle = '#7a7090';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh); ctx.fill(); ctx.stroke();
        ctx.fillStyle = 'rgba(160,145,180,0.7)';
        ctx.fillRect(-hw, -hh, sw, sh * 0.18);
        // Pillows
        const pw = Math.min(sw * 0.38, 50), ph = sh * 0.12;
        ctx.fillStyle = 'rgba(240,235,245,0.8)';
        ctx.strokeStyle = '#a090b0';
        ctx.lineWidth = 0.8;
        ctx.beginPath(); ctx.roundRect?.(-pw - 4, -hh + sh * 0.22, pw, ph, 3) || ctx.rect(-pw - 4, -hh + sh * 0.22, pw, ph);
        ctx.fill(); ctx.stroke();
        ctx.beginPath(); ctx.roundRect?.(4, -hh + sh * 0.22, pw, ph, 3) || ctx.rect(4, -hh + sh * 0.22, pw, ph);
        ctx.fill(); ctx.stroke();

      } else if (label.includes('desk') || label.includes('table')) {
        // Table/desk: rectangle with subtle grain
        ctx.fillStyle = 'rgba(210,185,145,0.45)';
        ctx.strokeStyle = '#8a7050';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh); ctx.fill(); ctx.stroke();
        ctx.strokeStyle = 'rgba(140,110,70,0.3)'; ctx.lineWidth = 0.5;
        ctx.beginPath(); ctx.moveTo(-hw + 4, 0); ctx.lineTo(hw - 4, 0); ctx.stroke();

      } else if (label.includes('toilet')) {
        // Toilet: tank rectangle + bowl oval
        ctx.fillStyle = 'rgba(230,235,240,0.7)';
        ctx.strokeStyle = '#8090a0';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh * 0.35); ctx.fill(); ctx.stroke();
        ctx.beginPath(); ctx.ellipse(0, hh - sh * 0.35, hw * 0.85, sh * 0.38, 0, 0, Math.PI * 2);
        ctx.fill(); ctx.stroke();

      } else if (label.includes('bathtub') || label.includes('bath')) {
        ctx.fillStyle = 'rgba(210,225,235,0.5)';
        ctx.strokeStyle = '#7090a0';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh); ctx.fill(); ctx.stroke();
        ctx.beginPath(); ctx.ellipse(0, sh * 0.08, hw * 0.72, hh * 0.65, 0, 0, Math.PI * 2);
        ctx.strokeStyle = 'rgba(100,140,170,0.5)'; ctx.stroke();

      } else if (label.includes('tv') || label.includes('television')) {
        // TV: thin panel
        ctx.fillStyle = 'rgba(40,40,50,0.7)';
        ctx.strokeStyle = '#303038';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh); ctx.fill(); ctx.stroke();
        ctx.strokeStyle = 'rgba(200,200,220,0.3)';
        ctx.beginPath(); ctx.rect(-hw + 3, -hh + 3, sw - 6, sh - 6); ctx.stroke();

      } else {
        // Generic furniture box
        ctx.fillStyle = 'rgba(200,195,185,0.3)';
        ctx.beginPath(); ctx.rect(-hw, -hh, sw, sh); ctx.fill(); ctx.stroke();
      }

      // Label
      ctx.fillStyle = '#5a5750';
      ctx.font = `${Math.max(8, Math.min(11, sw * 0.1))}px "DM Sans", sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.restore();

      // Draw label unrotated so it's always readable
      ctx.save();
      ctx.translate(cx, cy);
      ctx.fillStyle = '#5a5750';
      ctx.font = `${Math.max(7, Math.min(10, sw * 0.09))}px "DM Sans", sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(o.label || '', 0, 0);
      ctx.restore();
    });

    // Draw selection handles on top of all objects (in translated space)
    if (editMode && selectedIdx >= 0 && plan.objects[selectedIdx]) {
      drawEditHandles(plan.objects[selectedIdx]);
    }
  }

  // Draw dashed selection border + resize handles for the selected object
  function drawEditHandles(o) {
    const [cx, cy] = o.center;
    const [sw, sh] = o.scale || [40, 40];
    const hw = sw / 2, hh = sh / 2;

    // Dashed selection border
    ctx.save();
    ctx.strokeStyle = '#4a90e2';
    ctx.lineWidth = 1.5 / tscale;
    ctx.setLineDash([5 / tscale, 3 / tscale]);
    ctx.strokeRect(cx - hw, cy - hh, sw, sh);
    ctx.setLineDash([]);

    // 8px square handles at corners + edge midpoints (in plan space)
    const hSize = 8 / tscale;
    const handlePoints = [
      [cx - hw, cy - hh], [cx, cy - hh], [cx + hw, cy - hh],
      [cx - hw, cy],                      [cx + hw, cy],
      [cx - hw, cy + hh], [cx, cy + hh], [cx + hw, cy + hh],
    ];
    ctx.fillStyle = '#ffffff';
    ctx.strokeStyle = '#4a90e2';
    ctx.lineWidth = 1.5 / tscale;
    for (const [hx, hy] of handlePoints) {
      ctx.fillRect(hx - hSize/2, hy - hSize/2, hSize, hSize);
      ctx.strokeRect(hx - hSize/2, hy - hSize/2, hSize, hSize);
    }
    ctx.restore();

    // Update the edit bar label
    const labelEl = document.getElementById('fp-edit-label');
    if (labelEl) labelEl.textContent = o.label || o.class || 'Object';
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
    // --- Overall bounding box ---
    const dim = 30, tick = 5;
    const W = plan.width, H = plan.height;
    const mW = (W / plan.scale).toFixed(1);
    const mH = (H / plan.scale).toFixed(1);

    ctx.strokeStyle = '#c0bab2';
    ctx.fillStyle   = '#8a877f';
    ctx.lineWidth   = 0.7;
    ctx.font = '10px "DM Sans", sans-serif';

    ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(0, H + dim); ctx.lineTo(W, H + dim); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(0, H + dim - tick); ctx.lineTo(0, H + dim + tick);
    ctx.moveTo(W, H + dim - tick); ctx.lineTo(W, H + dim + tick);
    ctx.stroke();
    ctx.textAlign = 'center'; ctx.textBaseline = 'top';
    ctx.fillText(`${mW} m`, W / 2, H + dim + 5);

    ctx.setLineDash([2, 4]);
    ctx.beginPath(); ctx.moveTo(W + dim, 0); ctx.lineTo(W + dim, H); ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(W + dim - tick, 0); ctx.lineTo(W + dim + tick, 0);
    ctx.moveTo(W + dim - tick, H); ctx.lineTo(W + dim + tick, H);
    ctx.stroke();
    ctx.save();
    ctx.translate(W + dim + 13, H / 2);
    ctx.rotate(Math.PI / 2);
    ctx.textAlign = 'center'; ctx.textBaseline = 'bottom';
    ctx.fillText(`${mH} m`, 0, 0);
    ctx.restore();

    // --- Per-wall measurements ---
    drawPerWallDimensions();
  }

  function drawPerWallDimensions() {
    if (!plan?.rooms?.length) return;
    const S   = plan.scale || 100;
    const OFF = 14;   // offset from wall edge (plan coords)
    const TK  = 4;    // tick half-height

    ctx.save();

    // Track already-annotated wall midpoints to avoid duplicates on shared interior walls
    const seen = new Set();

    for (const room of plan.rooms) {
      const poly = room.poly;
      if (!poly || poly.length < 3) continue;

      // Room centroid (to determine outward direction)
      let rcx = 0, rcy = 0;
      for (const p of poly) { rcx += p[0]; rcy += p[1]; }
      rcx /= poly.length; rcy /= poly.length;

      for (let i = 0; i < poly.length; i++) {
        const p0 = poly[i];
        const p1 = poly[(i + 1) % poly.length];

        const dx = p1[0] - p0[0];
        const dy = p1[1] - p0[1];
        const len = Math.sqrt(dx * dx + dy * dy);
        if (len < 25) continue;  // skip walls < 0.25 m

        const meters = (len / S).toFixed(1);

        // Dedup: canonical edge key (sorted endpoints) so p0→p1 == p1→p0
        const SNAP = 4;
        const rnd = v => Math.round(v / SNAP) * SNAP;
        const [x0r, y0r, x1r, y1r] = [rnd(p0[0]), rnd(p0[1]), rnd(p1[0]), rnd(p1[1])];
        const key = x0r < x1r || (x0r === x1r && y0r <= y1r)
          ? `${x0r},${y0r},${x1r},${y1r}` : `${x1r},${y1r},${x0r},${y0r}`;
        if (seen.has(key)) continue;
        seen.add(key);

        // Outward normal away from room centroid
        const nx0 = -dy / len;
        const ny0 =  dx / len;
        const midX = (p0[0] + p1[0]) / 2;
        const midY = (p0[1] + p1[1]) / 2;
        const toCenter = (rcx - midX) * nx0 + (rcy - midY) * ny0;
        const sign = toCenter > 0 ? -1 : 1;
        const onx = nx0 * sign;
        const ony = ny0 * sign;

        // Dim line endpoints
        const ax = p0[0] + onx * OFF;
        const ay = p0[1] + ony * OFF;
        const bx = p1[0] + onx * OFF;
        const by = p1[1] + ony * OFF;

        // Dashed dim line
        ctx.strokeStyle = '#c0bab2';
        ctx.lineWidth = 0.7;
        ctx.setLineDash([2, 3]);
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
        ctx.setLineDash([]);

        // Tick marks (perpendicular to dim line = along wall direction)
        const ux = dx / len, uy = dy / len;
        ctx.strokeStyle = '#b0aaa2';
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(ax - uy * TK, ay + ux * TK);
        ctx.lineTo(ax + uy * TK, ay - ux * TK);
        ctx.moveTo(bx - uy * TK, by + ux * TK);
        ctx.lineTo(bx + uy * TK, by - ux * TK);
        ctx.stroke();

        // Text rotated along wall, always upright
        const tmx = (ax + bx) / 2;
        const tmy = (ay + by) / 2;
        let angle = Math.atan2(dy, dx);
        if (angle >  Math.PI / 2) angle -= Math.PI;
        if (angle < -Math.PI / 2) angle += Math.PI;

        ctx.save();
        ctx.translate(tmx, tmy);
        ctx.rotate(angle);
        ctx.fillStyle = '#7a7570';
        ctx.font = '8px "DM Sans", sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'bottom';
        ctx.fillText(`${meters} m`, 0, -2);
        ctx.restore();
      }
    }

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

  // ─── Edit mode ───────────────────────────────────────────────────────────────
  function setEditMode(on) {
    editMode = on; selectedIdx = -1; dragState = null;
    canvas.style.cursor = on ? 'default' : 'grab';
    document.getElementById('fp-edit')?.classList.toggle('active', on);
    const bar = document.getElementById('fp-edit-bar');
    if (bar) bar.style.display = on ? 'flex' : 'none';
    draw();
  }

  async function saveEdits() {
    try {
      await fetch('/floorplan/save', {
        method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify(plan),
      });
      showToast?.('Changes saved');
    } catch(e) { showToast?.('Save failed: ' + e.message); }
  }

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
  const THREE_CDN  = 'https://cdn.jsdelivr.net/npm/three@0.132.2/build/three.min.js';
  const ORBIT_CDN  = 'https://cdn.jsdelivr.net/npm/three@0.132.2/examples/js/controls/OrbitControls.js';

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
    renderer.outputEncoding = THREE.sRGBEncoding;
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

    // Walls — prefer room polygon (guaranteed closed) over wall array
    const wallPairs = [];
    if (p.rooms && p.rooms.length > 0 && p.rooms[0].poly?.length > 2) {
      const poly = p.rooms[0].poly;
      for (let i = 0; i < poly.length; i++) {
        wallPairs.push([poly[i], poly[(i + 1) % poly.length]]);
      }
    } else {
      (p.walls || []).forEach(w => wallPairs.push([w[0], w[1]]));
    }

    wallPairs.forEach(([p0, p1]) => {
      const x1 = p0[0] / S, z1 = p0[1] / S;
      const x2 = p1[0] / S, z2 = p1[1] / S;
      const dx = x2 - x1, dz = z2 - z1;
      const len = Math.sqrt(dx * dx + dz * dz);
      if (len < 0.05) return;
      const geo  = new THREE.BoxGeometry(len, WALL_H, WALL_T);
      const mesh = new THREE.Mesh(geo, wallMat);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.position.set((x1 + x2) / 2, WALL_H / 2, -(z1 + z2) / 2);
      mesh.rotation.y = -Math.atan2(dz, dx);
      scene.add(mesh);

      // Baseboard
      const baseGeo  = new THREE.BoxGeometry(len, 0.1, WALL_T + 0.01);
      const baseMesh = new THREE.Mesh(baseGeo,
        new THREE.MeshStandardMaterial({ color: 0xf8f4ee, roughness: 0.8 }));
      baseMesh.position.set((x1 + x2) / 2, 0.05, -(z1 + z2) / 2);
      baseMesh.rotation.y = -Math.atan2(dz, dx);
      scene.add(baseMesh);
    });

    // Window glass panes
    const glassMat = new THREE.MeshStandardMaterial({
      color: 0xadd8f0, transparent: true, opacity: 0.28,
      roughness: 0.05, metalness: 0.1, side: THREE.DoubleSide,
    });
    (p.windows || []).forEach(win => {
      const ww = (win.width || 80) / S;
      const wx = win.center[0] / S;
      const wz = win.center[1] / S;
      // Find closest wall to orient the glass
      let bestAngle = 0, bestDist = Infinity;
      wallPairs.forEach(([p0, p1]) => {
        const mx = (p0[0] + p1[0]) / (2 * S);
        const mz = (p0[1] + p1[1]) / (2 * S);
        const dist = Math.hypot(wx - mx, wz - mz);
        if (dist < bestDist) {
          bestDist = dist;
          bestAngle = Math.atan2((p1[1] - p0[1]) / S, (p1[0] - p0[0]) / S);
        }
      });
      const windowH = 1.2, windowY = 0.9;
      const geo  = new THREE.PlaneGeometry(ww, windowH);
      const mesh = new THREE.Mesh(geo, glassMat);
      mesh.position.set(wx, windowY + windowH / 2, -wz);
      mesh.rotation.y = -bestAngle;
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
      const mat = new THREE.MeshStandardMaterial({ color: type.color, roughness: 0.75, metalness: 0.05 });
      const px = ox / S, pz = -oy / S;
      const rot = -(o.rot || 0);

      const addMesh = (geo, yOffset = 0, overrideMat) => {
        const m = new THREE.Mesh(geo, overrideMat || mat);
        m.position.set(px, sh / 2 + yOffset, pz);
        m.rotation.y = rot;
        m.castShadow = true; m.receiveShadow = true;
        scene.add(m);
        return m;
      };

      if (type.shape === 'cylinder') {
        const r = Math.min(sw, sd) / 2;
        addMesh(new THREE.CylinderGeometry(r * 0.9, r, sh, 24));

      } else if (label.includes('sofa') || label.includes('couch')) {
        // Seat
        addMesh(new THREE.BoxGeometry(sw, sh * 0.55, sd * 0.65), -sh * 0.22);
        // Back cushion
        const backMat = new THREE.MeshStandardMaterial({ color: type.color - 0x101010, roughness: 0.8 });
        addMesh(new THREE.BoxGeometry(sw, sh * 0.75, sd * 0.28), sh * 0.125 - sh/2 + sh * 0.375, backMat);
        // Arms
        addMesh(new THREE.BoxGeometry(sd * 0.18, sh * 0.5, sd), 0);

      } else if (label.includes('bed')) {
        // Mattress
        const mattressMat = new THREE.MeshStandardMaterial({ color: 0xd8d0e8, roughness: 0.9 });
        addMesh(new THREE.BoxGeometry(sw, 0.25, sd), sh / 2 - 0.125, mattressMat);
        // Headboard
        const hbMat = new THREE.MeshStandardMaterial({ color: 0x8a7888, roughness: 0.6 });
        const hbMesh = new THREE.Mesh(new THREE.BoxGeometry(sw, sh * 0.85, 0.1), hbMat);
        hbMesh.position.set(px, sh * 0.425, pz + sd / 2 - 0.05);
        hbMesh.rotation.y = rot; hbMesh.castShadow = true;
        scene.add(hbMesh);

      } else if (label.includes('tv') || label.includes('television')) {
        // Thin screen panel
        const screenMat = new THREE.MeshStandardMaterial({ color: 0x101018, roughness: 0.2, metalness: 0.5 });
        addMesh(new THREE.BoxGeometry(sw, sh * 0.55, 0.06), 0, screenMat);
        // Stand
        const standMat = new THREE.MeshStandardMaterial({ color: 0x303030, roughness: 0.4 });
        addMesh(new THREE.BoxGeometry(sw * 0.15, sh * 0.4, 0.15), -sh * 0.28, standMat);

      } else {
        addMesh(new THREE.BoxGeometry(sw, sh, sd));
      }

      // Label sprite
      const sprite = makeLabel(THREE, o.label || key || 'object');
      sprite.position.set(px, sh + 0.3, pz);
      scene.add(sprite);
    });

    // Doors — panel pivoting from hinge, shown 40° open
    (p.doors || []).forEach(d => {
      const len = (d.len || 90) / S;
      const openAngle = (d.dir || 0) - Math.PI / 2 + Math.PI / 4.5; // ~40° open
      const [hx, hy] = d.hinge;
      const hx3 = hx / S, hz3 = -hy / S;

      // Door panel (offset so one end is at the hinge)
      const panelMat = new THREE.MeshStandardMaterial({ color: 0xd4b896, roughness: 0.55, metalness: 0.05 });
      const panelGeo = new THREE.BoxGeometry(len, WALL_H * 0.97, 0.045);
      const panel = new THREE.Mesh(panelGeo, panelMat);
      panel.position.set(
        hx3 + Math.cos(openAngle) * len / 2,
        WALL_H * 0.485,
        hz3 - Math.sin(openAngle) * len / 2
      );
      panel.rotation.y = -openAngle;
      panel.castShadow = true;
      scene.add(panel);

      // Door frame post at hinge
      const frameMat = new THREE.MeshStandardMaterial({ color: 0xf0ece4, roughness: 0.8 });
      const hinge3D = new THREE.Mesh(new THREE.BoxGeometry(0.07, WALL_H, 0.12), frameMat);
      hinge3D.position.set(hx3, WALL_H / 2, hz3);
      scene.add(hinge3D);

      // "Door" label above the panel
      const doorSprite = makeLabel(THREE, 'Door');
      doorSprite.position.set(
        hx3 + Math.cos(openAngle) * len / 2,
        WALL_H + 0.3,
        hz3 - Math.sin(openAngle) * len / 2
      );
      scene.add(doorSprite);
    });

    // Point light inside room
    const roomLight = new THREE.PointLight(0xfff5e0, 0.8, Math.max(W, H) * 2);
    roomLight.position.set(cx, WALL_H - 0.3, -cz);
    scene.add(roomLight);

    // Position camera at a corner looking across the room diagonally
    const dist = Math.max(W, H) * 0.95;
    camera.position.set(cx - dist * 0.55, dist * 0.65, -cz + dist * 0.7);
    controls.target.set(cx, 0.9, -cz);
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

  window.fpViewer = { loadPlan, fitView, resize, autoGenerate, spatialLMToFloorPlan, setEditMode };
})();
