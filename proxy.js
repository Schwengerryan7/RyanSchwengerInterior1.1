process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const express = require('express');
const app     = express();
const multer  = require('multer');
const path    = require('path');
const fs      = require('fs');

const ENDPOINT_ID       = '4qqf6weor3acy0';
const RECON_ENDPOINT_ID = 'obyg27dl14g8ws';
const RUNPOD_API_KEY    = process.env.RUNPOD_API_KEY;
const BASE_URL          = `https://api.runpod.ai/v2/${ENDPOINT_ID}`;
const RECON_URL         = `https://api.runpod.ai/v2/${RECON_ENDPOINT_ID}`;

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

app.use(express.json({ limit: '50mb' }));
app.use(express.static(__dirname));

// — Multer storage for video uploads
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const dir = './uploads';
    if (!fs.existsSync(dir)) fs.mkdirSync(dir);
    cb(null, dir);
  },
  filename: (req, file, cb) => {
    const timestamp = Date.now();
    cb(null, `scan_${timestamp}${path.extname(file.originalname)}`);
  }
});
const upload = multer({ storage, limits: { fileSize: 2 * 1024 * 1024 * 1024 } });

// — Health check
app.get('/health', (req, res) => res.json({ status: 'ok' }));

// — Scan route: receives video + prompt from scan.html
app.post('/scan', upload.single('video'), (req, res) => {
  const prompt = req.body.prompt || '';
  const file   = req.file;

  if (!file) {
    return res.status(400).json({ error: 'No video file received' });
  }

  const scanId = `scan_${Date.now()}`;

  console.log(`\n--- New Room Scan ---`);
  console.log(`Scan ID: ${scanId}`);
  console.log(`File:    ${file.filename} (${(file.size / 1024 / 1024).toFixed(1)} MB)`);
  console.log(`Prompt:  ${prompt}`);
  console.log(`Saved:   ${file.path}`);
  console.log(`---------------------\n`);

  // TODO: trigger Gaussian Splatting pipeline here once RunPod container is ready
  // Example: send to RunPod with the video path and prompt
  // fetch(`${RECON_URL}/run`, { method: 'POST', body: JSON.stringify({ input: { video: file.path, prompt } }) })

  res.json({
    success: true,
    message: 'Video received — processing queued',
    scanId,
    file:   file.filename,
    prompt
  });
});

// — List saved scans
app.get('/scans', (req, res) => {
  const dir = './uploads';
  if (!fs.existsSync(dir)) return res.json({ scans: [] });
  const files = fs.readdirSync(dir).map(f => ({
    name: f,
    size: (fs.statSync(path.join(dir, f)).size / 1024 / 1024).toFixed(1) + ' MB',
    created: fs.statSync(path.join(dir, f)).birthtime
  }));
  res.json({ scans: files });
});

// — Material render route (existing)
app.post('/run', async (req, res) => {
  try {
    const { default: fetch } = await import('node-fetch');
    const r = await fetch(`${BASE_URL}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${RUNPOD_API_KEY}` },
      body: JSON.stringify(req.body)
    });
    const body = await r.json();
    console.log('RunPod /run status:', r.status, JSON.stringify(body).slice(0, 300));
    res.status(r.status).json(body);
  } catch (e) {
    console.error('RunPod /run error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

// — Reconstruction run route (existing)
app.post('/recon/run', async (req, res) => {
  try {
    const { default: fetch } = await import('node-fetch');
    const r = await fetch(`${RECON_URL}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${RUNPOD_API_KEY}` },
      body: JSON.stringify(req.body)
    });
    const body = await r.json();
    console.log('Recon /run status:', r.status, JSON.stringify(body).slice(0, 300));
    res.status(r.status).json(body);
  } catch (e) {
    console.error('Recon /run error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

// — Reconstruction status route (existing)
app.get('/recon/status/:id', async (req, res) => {
  try {
    const { default: fetch } = await import('node-fetch');
    const r = await fetch(`${RECON_URL}/status/${req.params.id}`, {
      headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
    });
    const body = await r.json();
    res.status(r.status).json(body);
  } catch (e) {
    console.error('Recon /status error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

// — Material render status route (existing)
app.get('/status/:id', async (req, res) => {
  try {
    const { default: fetch } = await import('node-fetch');
    const r = await fetch(`${BASE_URL}/status/${req.params.id}`, {
      headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
    });
    const body = await r.json();
    console.log('RunPod /status:', r.status, JSON.stringify(body).slice(0, 200));
    res.status(r.status).json(body);
  } catch (e) {
    console.error('RunPod /status error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

app.listen(3001, () => {
  console.log('Proxy running on http://localhost:3001');
  console.log('API key set:', !!RUNPOD_API_KEY);
});