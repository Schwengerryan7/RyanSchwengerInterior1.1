 process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';                                                                                     
  const express = require('express');                                                                                                 
  const app     = express();                                                                                                          
                                                                                                                                      
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

  app.get('/health', (req, res) => res.json({ status: 'ok' }));                                                                       
   
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
