process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
const express = require('express');
const app     = express();
const multer  = require('multer');
const path    = require('path');
const fs      = require('fs');

const ENDPOINT_ID       = '4qqf6weor3acy0';
const RECON_ENDPOINT_ID = 'obyg27dl14g8ws';
const GS_ENDPOINT_ID    = process.env.GS_ENDPOINT_ID || 'ppgrpcsc18rzc8';
const RUNPOD_API_KEY    = process.env.RUNPOD_API_KEY;
const BASE_URL          = `https://api.runpod.ai/v2/${ENDPOINT_ID}`;
const RECON_URL         = `https://api.runpod.ai/v2/${RECON_ENDPOINT_ID}`;
const GS_URL            = `https://api.runpod.ai/v2/${GS_ENDPOINT_ID}`;

app.use((req, res, next) => {
  res.header('Access-Control-Allow-Origin', '*');
  res.header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.header('Access-Control-Allow-Headers', 'Content-Type, Authorization');
  if (req.method === 'OPTIONS') return res.sendStatus(200);
  next();
});

app.use(express.json({ limit: '50mb' }));
app.use(express.static(__dirname));

// — Multer: save uploaded videos to ./uploads/
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    const dir = './uploads';
    if (!fs.existsSync(dir)) fs.mkdirSync(dir);
    cb(null, dir);
  },
  filename: (req, file, cb) => {
    cb(null, `scan_${Date.now()}${path.extname(file.originalname)}`);
  }
});
const upload = multer({ storage, limits: { fileSize: 2 * 1024 * 1024 * 1024 } });

// — Health check
app.get('/health', (req, res) => res.json({ status: 'ok' }));

// ─────────────────────────────────────────────
// /scan — receive video, send to RunPod GS endpoint
// ─────────────────────────────────────────────
app.post('/scan', upload.single('video'), async (req, res) => {
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

  try {
    const { default: fetch } = await import('node-fetch');

    // Read video and encode as base64
    const videoBuffer = fs.readFileSync(file.path);
    const video_b64   = videoBuffer.toString('base64');

    console.log(`Sending to RunPod GS endpoint: ${GS_ENDPOINT_ID}`);

    // Send to RunPod Gaussian Splatting endpoint
    const response = await fetch(`${GS_URL}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${RUNPOD_API_KEY}`
      },
      body: JSON.stringify({
        input: {
          video_b64,
          prompt,
          filename: file.originalname,
          scan_id:  scanId
        }
      })
    });

    const body = await response.json();
    console.log('RunPod GS job submitted:', body.id);

    // Return the job ID so frontend can poll for status
    res.json({
      success: true,
      scanId,
      jobId:   body.id,
      message: 'Video sent to Gaussian Splatting pipeline'
    });

  } catch (err) {
    console.error('Scan error:', err.message);
    res.status(500).json({ error: err.message });
  }
});

// ─────────────────────────────────────────────
// /scan/status/:jobId — poll GS job status
// ─────────────────────────────────────────────
app.get('/scan/status/:jobId', async (req, res) => {
  try {
    const { default: fetch } = await import('node-fetch');
    const r = await fetch(`${GS_URL}/status/${req.params.jobId}`, {
      headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
    });
    const body = await r.json();

    // If complete, save the .ply file locally
    if (body.status === 'COMPLETED' && body.output?.ply_b64) {
      const plyDir = './splats';
      if (!fs.existsSync(plyDir)) fs.mkdirSync(plyDir);
      const plyPath = `${plyDir}/${req.params.jobId}.ply`;
      fs.writeFileSync(plyPath, Buffer.from(body.output.ply_b64, 'base64'));
      console.log(`PLY saved: ${plyPath} (${body.output.ply_size_mb} MB)`);

      return res.json({
        status:  'COMPLETED',
        plyUrl:  `/splats/${req.params.jobId}.ply`,
        sizeMb:  body.output.ply_size_mb,
        frames:  body.output.frame_count,
        message: body.output.message
      });
    }

    res.json({ status: body.status, jobId: req.params.jobId });

  } catch (e) {
    console.error('GS status error:', e.message);
    res.status(500).json({ error: e.message });
  }
});

// Serve saved .ply files
app.use('/splats', express.static('./splats'));

// — List saved scans
app.get('/scans', (req, res) => {
  const dir = './uploads';
  if (!fs.existsSync(dir)) return res.json({ scans: [] });
  const files = fs.readdirSync(dir).map(f => ({
    name:    f,
    size:    (fs.statSync(path.join(dir, f)).size / 1024 / 1024).toFixed(1) + ' MB',
    created: fs.statSync(path.join(dir, f)).birthtime
  }));
  res.json({ scans: files });
});

// — Material render (existing)
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

// — Reconstruction run (existing)
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

// — Reconstruction status (existing)
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

// — Material render status (existing)
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
  console.log('GS Endpoint:', GS_ENDPOINT_ID);
});