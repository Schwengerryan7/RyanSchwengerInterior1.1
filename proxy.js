const express = require('express');
const cors = require('cors');
const fetch = (...args) => import('node-fetch').then(({default: f}) => f(...args));

const app = express();
app.use(cors());
app.use(express.json({ limit: '50mb' }));

const RUNPOD_API_KEY = process.env.RUNPOD_API_KEY;
const ENDPOINT_ID = '4qqf6weor3acy0';

app.post('/run', async (req, res) => {
  const r = await fetch(`https://api.runpod.ai/v2/${ENDPOINT_ID}/run`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${RUNPOD_API_KEY}` },
    body: JSON.stringify(req.body)
  });
  res.json(await r.json());
});

app.get('/status/:id', async (req, res) => {
  const r = await fetch(`https://api.runpod.ai/v2/${ENDPOINT_ID}/status/${req.params.id}`, {
    headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
  });
  res.json(await r.json());
});

app.listen(3001, () => console.log('Proxy running on port 3001'));
