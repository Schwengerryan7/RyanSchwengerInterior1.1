(function () {
  'use strict';

  // Demo 2-bed apartment — 10m × 8m, all coordinates in cm
  const DEMO = {
    width: 1000,
    height: 800,
    scale: 100, // cm per meter
    rooms: [
      {
        label: 'Living / Dining', area: 30, color: '#f5f0e8',
        poly: [[0,0],[600,0],[600,500],[0,500]]
      },
      {
        label: 'Kitchen', area: 12, color: '#eaf0e8',
        poly: [[600,0],[1000,0],[1000,300],[600,300]]
      },
      {
        label: 'Master Bedroom', area: 20, color: '#e8eaf5',
        poly: [[600,300],[1000,300],[1000,800],[600,800]]
      },
      {
        label: 'Bedroom', area: 12, color: '#e8eaf5',
        poly: [[0,500],[400,500],[400,800],[0,800]]
      },
      {
        label: 'Bathroom', area: 5, color: '#ddf0ec',
        poly: [[400,500],[600,500],[600,750],[400,750]]
      },
      {
        label: 'Entry', area: 1, color: '#eeece8',
        poly: [[400,750],[600,750],[600,800],[400,800]]
      },
    ],
    walls: [
      // Perimeter
      [[0,0],[1000,0]], [[1000,0],[1000,800]],
      [[1000,800],[0,800]], [[0,800],[0,0]],
      // Interior
      [[600,0],[600,800]],
      [[0,500],[600,500]],
      [[400,500],[400,800]],
      [[600,300],[1000,300]],
      [[400,750],[600,750]],
    ],
    // hinge: [x,y], len: door width in cm, dir: angle of open leaf (radians, canvas coords)
    doors: [
      { hinge: [460,0],   len: 90, dir: Math.PI / 2 },       // Front entry, opens south
      { hinge: [600,120], len: 80, dir: 0 },                   // Living→Kitchen, opens east
      { hinge: [780,300], len: 80, dir: Math.PI / 2 },        // Kitchen→Master, opens south
      { hinge: [100,500], len: 80, dir: Math.PI / 2 },        // Living→Bedroom, opens south
      { hinge: [400,580], len: 70, dir: 0 },                   // Bathroom door, opens east
    ],
  };

  let canvas, ctx;
  let plan = null;
  let tx = 0, ty = 0, tscale = 1;
  let panning = false, panStart = null;

  function init() {
    canvas = document.getElementById('fp-canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    window.addEventListener('resize', resize);

    canvas.addEventListener('wheel', onWheel, { passive: false });
    canvas.addEventListener('mousedown', onMouseDown);
    canvas.addEventListener('mousemove', onMouseMove);
    canvas.addEventListener('mouseup', onMouseUp);
    canvas.addEventListener('mouseleave', onMouseUp);
    canvas.addEventListener('dragover', e => e.preventDefault());
    canvas.addEventListener('drop', onDrop);

    document.getElementById('fp-fit')?.addEventListener('click', fitView);
    document.getElementById('fp-zoom-in')?.addEventListener('click', () => zoomAt(canvas.width / 2, canvas.height / 2, 1.25));
    document.getElementById('fp-zoom-out')?.addEventListener('click', () => zoomAt(canvas.width / 2, canvas.height / 2, 0.8));
    document.getElementById('fp-export-png')?.addEventListener('click', exportPNG);
    document.getElementById('fp-generate')?.addEventListener('click', onGenerate);

    loadPlan(DEMO);
  }

  // ─── Public API ──────────────────────────────
  function resize() {
    if (!canvas) return;
    const w = canvas.offsetWidth;
    const h = canvas.offsetHeight;
    if (!w || !h || (canvas.width === w && canvas.height === h)) return;
    canvas.width = w;
    canvas.height = h;
    if (plan) fitView();
    else draw();
  }

  function loadPlan(p) {
    plan = p;
    // Next rAF: canvas may not have layout yet when called on init
    requestAnimationFrame(() => { resize(); fitView(); });
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

  // ─── Zoom / Pan ──────────────────────────────
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

  function onMouseUp() {
    panning = false;
    canvas.style.cursor = 'grab';
  }

  // ─── Drop ────────────────────────────────────
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
    } else {
      showToast?.('Drop a .json floor plan file, or use Generate');
    }
  }

  // ─── Generate stub ───────────────────────────
  function onGenerate() {
    showToast?.('Floor plan generation needs the backend service — coming soon!');
  }

  // ─── Export ──────────────────────────────────
  function exportPNG() {
    const a = document.createElement('a');
    a.download = 'floor-plan.png';
    a.href = canvas.toDataURL('image/png');
    a.click();
  }

  // ─── Draw ────────────────────────────────────
  function draw() {
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Paper background
    ctx.fillStyle = '#f7f6f4';
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    if (!plan) { drawPlaceholder(); return; }

    ctx.save();
    ctx.translate(tx, ty);
    ctx.scale(tscale, tscale);

    drawRooms();
    drawWalls();
    drawDoors();
    drawLabels();
    drawDimensions();

    ctx.restore();
    drawScaleBar();
    drawNorthArrow();
  }

  function drawPlaceholder() {
    ctx.fillStyle = '#8a877f';
    ctx.font = '14px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Drop a .json floor plan or click Generate', canvas.width / 2, canvas.height / 2);
  }

  function drawRooms() {
    plan.rooms.forEach(r => {
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
    ctx.lineWidth = 8;
    plan.walls.forEach(w => {
      ctx.beginPath();
      ctx.moveTo(w[0][0], w[0][1]);
      ctx.lineTo(w[1][0], w[1][1]);
      ctx.stroke();
    });
  }

  function drawDoors() {
    ctx.strokeStyle = '#2a2825';
    ctx.lineWidth = 1.5;
    plan.doors.forEach(d => {
      const [hx, hy] = d.hinge;
      const ex = hx + Math.cos(d.dir) * d.len;
      const ey = hy + Math.sin(d.dir) * d.len;

      // Door leaf (open position)
      ctx.beginPath();
      ctx.moveTo(hx, hy);
      ctx.lineTo(ex, ey);
      ctx.stroke();

      // Swing arc from perpendicular (closed) to open
      ctx.beginPath();
      ctx.arc(hx, hy, d.len, d.dir - Math.PI / 2, d.dir, false);
      ctx.setLineDash([3, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
    });
  }

  function drawLabels() {
    plan.rooms.forEach(r => {
      if (!r.label) return;
      const xs = r.poly.map(p => p[0]);
      const ys = r.poly.map(p => p[1]);
      const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
      const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
      const roomW = Math.max(...xs) - Math.min(...xs);

      const fs = Math.max(10, Math.min(16, roomW * 0.075));
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
    // Outer width + height dimension lines
    const dimOffset = 28;
    const tickLen   = 6;
    ctx.strokeStyle = '#b0aba0';
    ctx.fillStyle   = '#8a877f';
    ctx.lineWidth   = 0.8;
    ctx.setLineDash([2, 3]);

    const W = plan.width, H = plan.height;
    const mW = (W / plan.scale).toFixed(1);
    const mH = (H / plan.scale).toFixed(1);

    // Bottom dimension (width)
    ctx.beginPath();
    ctx.moveTo(0, H + dimOffset);
    ctx.lineTo(W, H + dimOffset);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(0, H + dimOffset - tickLen); ctx.lineTo(0, H + dimOffset + tickLen);
    ctx.moveTo(W, H + dimOffset - tickLen); ctx.lineTo(W, H + dimOffset + tickLen);
    ctx.stroke();
    ctx.font = '11px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(`${mW} m`, W / 2, H + dimOffset + 4);

    // Right dimension (height)
    ctx.setLineDash([2, 3]);
    ctx.beginPath();
    ctx.moveTo(W + dimOffset, 0);
    ctx.lineTo(W + dimOffset, H);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(W + dimOffset - tickLen, 0); ctx.lineTo(W + dimOffset + tickLen, 0);
    ctx.moveTo(W + dimOffset - tickLen, H); ctx.lineTo(W + dimOffset + tickLen, H);
    ctx.stroke();
    ctx.save();
    ctx.translate(W + dimOffset + 14, H / 2);
    ctx.rotate(Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`${mH} m`, 0, 0);
    ctx.restore();
  }

  function drawScaleBar() {
    if (!plan) return;
    const meterPx = tscale * plan.scale;
    // Pick a bar length that's between 60–160px
    let barMeters = 1;
    if (meterPx * 5 < 160) barMeters = 5;
    if (meterPx * 2 < 160) barMeters = 2;
    const barPx = barMeters * meterPx;

    const x = 20, y = canvas.height - 20;
    ctx.strokeStyle = '#1a1916';
    ctx.lineWidth = 1.5;
    ctx.lineCap = 'butt';
    ctx.beginPath();
    ctx.moveTo(x, y - 5); ctx.lineTo(x, y);
    ctx.lineTo(x + barPx, y);
    ctx.lineTo(x + barPx, y - 5);
    ctx.stroke();

    ctx.fillStyle = '#1a1916';
    ctx.font = '10px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`${barMeters} m`, x + barPx / 2, y - 6);
  }

  function drawNorthArrow() {
    const x = canvas.width - 24, y = canvas.height - 30;
    ctx.fillStyle = '#1a1916';
    ctx.strokeStyle = '#1a1916';
    ctx.lineWidth = 1;

    // Arrow head pointing up (north)
    ctx.beginPath();
    ctx.moveTo(x, y - 14);
    ctx.lineTo(x - 5, y + 6);
    ctx.lineTo(x, y + 1);
    ctx.lineTo(x + 5, y + 6);
    ctx.closePath();
    ctx.fill();

    ctx.font = 'bold 9px "DM Sans", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.fillText('N', x, y - 16);
  }

  // ─── Boot ────────────────────────────────────
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.fpViewer = { loadPlan, fitView, resize };
})();
