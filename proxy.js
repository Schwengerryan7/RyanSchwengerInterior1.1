 process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
  const express   = require('express');
  const Anthropic = require('@anthropic-ai/sdk');
  const app       = express();
  const anthropic = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });                                                                                                          
                                                                                                                                      
  const ENDPOINT_ID       = '4qqf6weor3acy0';
  const RECON_ENDPOINT_ID = 'obyg27dl14g8ws';
  const SPLAT_ENDPOINT_ID = process.env.SPLAT_ENDPOINT_ID || 'l4cc89v4me7yg4';
  const FP_ENDPOINT_ID    = process.env.FP_ENDPOINT_ID    || 'cliyu9anwshcle';
  const RUNPOD_API_KEY    = process.env.RUNPOD_API_KEY;
  const BASE_URL          = `https://api.runpod.ai/v2/${ENDPOINT_ID}`;
  const RECON_URL         = `https://api.runpod.ai/v2/${RECON_ENDPOINT_ID}`;
  const SPLAT_URL         = `https://api.runpod.ai/v2/${SPLAT_ENDPOINT_ID}`;
  const FP_URL            = `https://api.runpod.ai/v2/${FP_ENDPOINT_ID}`;                                                          
                                                                                                                                    
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
                                                                                                                                    
  app.post('/splat/run', async (req, res) => {
    if (SPLAT_ENDPOINT_ID === 'YOUR_SPLAT_ENDPOINT_ID') {
      return res.status(503).json({ error: 'GS endpoint not configured. Set SPLAT_ENDPOINT_ID env var, or drop a .ply file directly into the Floor Plan tab.' });
    }
    try {
      const { default: fetch } = await import('node-fetch');
      const r = await fetch(`${SPLAT_URL}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${RUNPOD_API_KEY}` },
        body: JSON.stringify(req.body)
      });
      const body = await r.json();
      console.log('Splat /run status:', r.status, JSON.stringify(body).slice(0, 300));
      res.status(r.status).json(body);
    } catch (e) {
      console.error('Splat /run error:', e.message);
      res.status(500).json({ error: e.message });
    }
  });

  app.get('/splat/status/:id', async (req, res) => {
    try {
      const { default: fetch } = await import('node-fetch');
      const r = await fetch(`${SPLAT_URL}/status/${req.params.id}`, {
        headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` }
      });
      const body = await r.json();
      res.status(r.status).json(body);
    } catch (e) {
      console.error('Splat /status error:', e.message);
      res.status(500).json({ error: e.message });
    }
  });

  // ── Floor plan (PTv3 + RoomFormer) ───────────────────────────────────────────
  app.post('/floorplan/run', express.json({ limit: '200mb' }), async (req, res) => {
    try {
      const { default: fetch } = await import('node-fetch');
      const r = await fetch(`${FP_URL}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${RUNPOD_API_KEY}` },
        body: JSON.stringify({ input: req.body }),
      });
      const body = await r.json();
      console.log('FP /run status:', r.status, JSON.stringify(body).slice(0, 200));
      res.status(r.status).json(body);
    } catch (e) {
      console.error('FP /run error:', e.message);
      res.status(500).json({ error: e.message });
    }
  });

  // Serve the latest saved floor plan JSON
  app.get('/floorplan/latest', (req, res) => {
    const path = require('path');
    const fs   = require('fs');
    const fp   = path.join(__dirname, 'floor_plan.json');
    if (!fs.existsSync(fp)) return res.status(404).json({ error: 'No floor plan saved yet' });
    res.json(JSON.parse(fs.readFileSync(fp, 'utf8')));
  });

  app.get('/floorplan/status/:id', async (req, res) => {
    try {
      const { default: fetch } = await import('node-fetch');
      const r = await fetch(`${FP_URL}/status/${req.params.id}`, {
        headers: { 'Authorization': `Bearer ${RUNPOD_API_KEY}` },
      });
      const body = await r.json();
      res.status(r.status).json(body);
    } catch (e) {
      console.error('FP /status error:', e.message);
      res.status(500).json({ error: e.message });
    }
  });

  // ── Claude Vision floor plan ─────────────────────────────────────────────────
  const FLOOR_PLAN_PROMPT = `You are an expert architectural surveyor. Analyze these video frames of a room walkthrough and produce a precise architectural floor plan in JSON.

STEP 1 — IDENTIFY THE ROOM TYPE
Look at all the frames and determine what kind of room this is: Bedroom, Living Room, Kitchen, Bathroom, Office, Dining Room, etc. Use the dominant furniture and fixtures to decide.

STEP 2 — CALIBRATE SCALE
Use these known reference dimensions to estimate room size:
- Interior door: 0.8–0.9 m wide × 2.1 m tall (most reliable reference)
- Ceiling height: 2.4–2.7 m
- Single bed: 0.9×1.9 m | Double: 1.35×1.9 m | Queen: 1.52×2.03 m | King: 1.83×2.03 m
- Sofa: 1.8–2.5 m wide × 0.85–0.95 m deep
- Dining chair: 0.45×0.45 m | Dining table for 4: ~1.2×0.8 m
- Kitchen counter depth: 0.6 m
- Standard window: 0.9–1.5 m wide

STEP 3 — TRACE THE ROOM PERIMETER
Starting at the bottom-left corner, trace the room boundary clockwise. Include every corner — alcoves, offsets, bay windows, anything that changes the wall line.

STEP 4 — PLACE ALL OBJECTS
For every visible piece of furniture or fixture, record its center position within the room, its real-world dimensions, and its facing direction.

Output ONLY this JSON (no markdown, no commentary, no backticks):
{
  "rooms": [{"label": "Bedroom", "poly": [[0,0],[3.6,0],[3.6,4.5],[0,4.5]], "area": 16.2}],
  "walls": [
    {"id":"w0","start":[0,0],"end":[3.6,0],"height":2.5},
    {"id":"w1","start":[3.6,0],"end":[3.6,4.5],"height":2.5},
    {"id":"w2","start":[3.6,4.5],"end":[0,4.5],"height":2.5},
    {"id":"w3","start":[0,4.5],"end":[0,0],"height":2.5}
  ],
  "doors": [{"position":[0.45,0],"width":0.9,"wall_dir":0}],
  "windows": [{"position":[2.5,4.5],"width":1.1}],
  "objects": [
    {"class":"bed","center":[1.2,3.2],"rotation":0,"scale":[1.52,2.03]},
    {"class":"wardrobe","center":[3.2,1.0],"rotation":0,"scale":[1.2,0.6]},
    {"class":"desk","center":[0.5,1.0],"rotation":0,"scale":[1.2,0.6]}
  ],
  "bounds": {"min_x":0,"min_y":0,"max_x":3.6,"max_y":4.5,"width":3.6,"height":4.5}
}

DOORS:
- Only include doors you can clearly see (door frame, handle, knob, or gap under door)
- Standard interior door width: 0.8–0.9 m. Anything wider than 1.0 m is a window or archway, not a door
- If the same door appears in multiple frames, count it once
- When in doubt, omit — a false door is worse than a missing one

RULES:
- rooms[0].label = the room type you identified in Step 1 (e.g. "Bedroom", "Living Room", "Kitchen")
- rooms[0].poly = exact room perimeter traced clockwise — every corner, no approximation
- walls = one entry per polygon edge, start/end must match poly corners exactly
- doors.position = center of the door opening (not the hinge)
- doors.wall_dir = wall angle in radians: 0 = horizontal wall (along X), π/2 ≈ 1.5708 = vertical wall (along Y)
- objects.center = must be strictly inside bounds — never on or beyond a wall
- objects.scale = [width, depth] in meters — realistic sizes, not [1,1]
- objects.rotation = radians clockwise from +Y axis (0 = object faces up in plan view)
- bounds = exact min/max of the room polygon
- Return ONLY the raw JSON object`;

  // ── Helper: parse JSON from Claude response (handles markdown fences) ─────────
  function parseFloorPlanJSON(text) {
    const m = text.match(/```json\s*([\s\S]*?)```/) ||
              text.match(/```\s*([\s\S]*?)```/)     ||
              text.match(/(\{[\s\S]*\})/);
    return JSON.parse(m ? m[1] : text);
  }

  // ── Helper: single Claude API call with images ────────────────────────────────
  function callClaude(anthropicClient, images, prompt, maxTokens = 2048) {
    return anthropicClient.messages.create({
      model: 'claude-opus-4-7', max_tokens: maxTokens,
      messages: [{ role: 'user', content: [
        ...images.map(f => ({ type: 'image', source: { type: 'base64', media_type: 'image/jpeg', data: f } })),
        { type: 'text', text: prompt },
      ]}],
    }).then(r => r.content[0].text.trim());
  }

  // ── Helper: one furniture pass with a given frame subset ─────────────────────
  async function runFurniturePass(anthropicClient, frames, geo) {
    const b = geo.bounds || {};
    const objPrompt = `You are placing furniture in a floor plan.

The room has already been measured:
- Type: ${geo.rooms?.[0]?.label || 'Room'}
- Width: ${(b.width||0).toFixed(2)} m (X axis: 0 to ${(b.max_x||0).toFixed(2)})
- Depth: ${(b.height||0).toFixed(2)} m (Y axis: 0 to ${(b.max_y||0).toFixed(2)})

Analyze these frames and list every visible piece of furniture and fixture.
For each object give its center position strictly within the room bounds, realistic scale, and rotation.

Output ONLY this JSON (no markdown, no commentary):
{"objects":[{"class":"sofa","center":[x,y],"rotation":0,"scale":[width,depth]}]}

Rules:
- center must satisfy: ${(b.min_x||0).toFixed(2)} < x < ${(b.max_x||0).toFixed(2)} AND ${(b.min_y||0).toFixed(2)} < y < ${(b.max_y||0).toFixed(2)}
- scale = [width, depth] in real meters — use known sizes (bed ≈ 1.52×2.03m, sofa ≈ 2.1×0.9m, chair ≈ 0.5×0.5m)
- rotation = radians clockwise from +Y
- List every item you can see — bed, desk, chair, wardrobe, tv, lamp, shelf, plant, etc.
- Do not include walls, doors, or windows — only furniture and objects`;

    const text = await callClaude(anthropicClient, frames, objPrompt, 2048);
    const result = parseFloorPlanJSON(text);
    return result.objects || [];
  }

  // ── Helper: consensus across 3 furniture runs ─────────────────────────────────
  // Groups objects by class + proximity (within 0.6m = same object).
  // Keeps only objects seen in 2+ of the 3 runs; uses median center per cluster.
  function consensusFurniture(allRuns) {
    // Union + merge: keep all objects, merge same-class objects within 1.0m, take median position.
    // This stabilises coordinates across runs without dropping real objects that Claude
    // happened to place slightly differently in different frame subsets.
    const all = allRuns.flat();
    const used = new Set();
    const merged = [];

    for (let i = 0; i < all.length; i++) {
      if (used.has(i)) continue;
      const seed = all[i];
      const cluster = [seed];
      used.add(i);

      for (let j = i + 1; j < all.length; j++) {
        if (used.has(j)) continue;
        const cand = all[j];
        if (cand.class !== seed.class) continue;
        if (Math.hypot(cand.center[0]-seed.center[0], cand.center[1]-seed.center[1]) < 1.0) {
          cluster.push(cand);
          used.add(j);
        }
      }

      const xs  = cluster.map(o => o.center[0]).sort((a,b) => a-b);
      const ys  = cluster.map(o => o.center[1]).sort((a,b) => a-b);
      const mid = Math.floor(cluster.length / 2);
      const rep = cluster[mid];
      merged.push({ class: rep.class, center: [xs[mid], ys[mid]], rotation: rep.rotation||0, scale: rep.scale });
    }

    console.log(`[Claude FP] Consensus: ${all.length} raw → ${merged.length} merged objects`);
    return merged;
  }

  app.post('/claude-floorplan/run', express.json({ limit: '100mb' }), async (req, res) => {
    try {
      const { frames } = req.body;  // array of base64 JPEG strings (no data: prefix)
      if (!frames || frames.length === 0) return res.status(400).json({ error: 'No frames provided' });

      console.log(`[Claude FP] Pass 1/2: geometry analysis (${frames.length} frames)...`);

      // ── Pass 1: room geometry only (8 evenly-spaced frames) ──────────────────
      const geoFrames = frames.filter((_, i) => i % Math.ceil(frames.length / 8) === 0).slice(0, 8);
      const geoPrompt = `${FLOOR_PLAN_PROMPT}

IMPORTANT: Output ONLY the room geometry — rooms, walls, doors, windows, bounds.
Do NOT include any furniture or objects. The "objects" field must be an empty array [].
Focus all your attention on getting the room shape, dimensions, and wall positions exactly right.`;

      const geoText = await callClaude(anthropic, geoFrames, geoPrompt, 1500);
      console.log('[Claude FP] Geometry response:', geoText.slice(0, 200));
      const geo = parseFloorPlanJSON(geoText);

      // Snap room to rectangle if it's close enough (most rooms are rectangular)
      if (geo.rooms?.[0]?.poly) {
        const poly = geo.rooms[0].poly;
        const xs = poly.map(p => p[0]), ys = poly.map(p => p[1]);
        const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
        const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
        // If all corners are within 0.25m of the axis-aligned bounding box, snap to rectangle
        const nearRect = poly.every(([x,y]) =>
          (Math.abs(x-x0)<0.25 || Math.abs(x-x1)<0.25) &&
          (Math.abs(y-y0)<0.25 || Math.abs(y-y1)<0.25)
        );
        if (nearRect && poly.length <= 6) {
          geo.rooms[0].poly = [[x0,y0],[x1,y0],[x1,y1],[x0,y1]];
          geo.bounds = { min_x:x0, min_y:y0, max_x:x1, max_y:y1, width:x1-x0, height:y1-y0 };
          const wh = geo.walls?.[0]?.height || 2.5;
          geo.walls = [
            {id:'w0',start:[x0,y0],end:[x1,y0],height:wh},
            {id:'w1',start:[x1,y0],end:[x1,y1],height:wh},
            {id:'w2',start:[x1,y1],end:[x0,y1],height:wh},
            {id:'w3',start:[x0,y1],end:[x0,y0],height:wh},
          ];
          console.log(`[Claude FP] Snapped to rectangle: ${(x1-x0).toFixed(2)}×${(y1-y0).toFixed(2)}m`);
        }
      }

      // ── Pass 2: furniture — 3 parallel runs with different shuffled frame subsets ──
      console.log('[Claude FP] Pass 2/2: furniture analysis (3 parallel runs)...');

      // Shuffle helper
      const shuffle = arr => {
        const a = [...arr];
        for (let i = a.length - 1; i > 0; i--) {
          const j = Math.floor(Math.random() * (i + 1));
          [a[i], a[j]] = [a[j], a[i]];
        }
        return a;
      };

      // Build 3 different ~15-frame subsets (shuffled each time)
      const subsetSize = Math.min(15, frames.length);
      const subsets = [
        shuffle(frames).slice(0, subsetSize),
        shuffle(frames).slice(0, subsetSize),
        shuffle(frames).slice(0, subsetSize),
      ];

      // Run 3 furniture passes in parallel
      const [run0, run1, run2] = await Promise.all([
        runFurniturePass(anthropic, subsets[0], geo).catch(e => { console.error('[Claude FP] Run 0 error:', e.message); return []; }),
        runFurniturePass(anthropic, subsets[1], geo).catch(e => { console.error('[Claude FP] Run 1 error:', e.message); return []; }),
        runFurniturePass(anthropic, subsets[2], geo).catch(e => { console.error('[Claude FP] Run 2 error:', e.message); return []; }),
      ]);
      console.log(`[Claude FP] Furniture runs: ${run0.length} / ${run1.length} / ${run2.length} objects`);

      // Apply consensus (majority vote + median position)
      const consensusObjects = consensusFurniture([run0, run1, run2]);
      console.log(`[Claude FP] Consensus: ${consensusObjects.length} objects kept from ${run0.length + run1.length + run2.length} total`);

      // Merge geometry + consensus furniture
      const fp = { ...geo, objects: consensusObjects };

      // ── Post-processing ───────────────────────────────────────────────────────
      const { min_x=0, max_x=10, min_y=0, max_y=8 } = fp.bounds || {};

      // Snap all coordinates to 0.05m grid
      const snap = v => Math.round(v / 0.05) * 0.05;
      (fp.doors || []).forEach(d => { d.position = d.position.map(snap); });
      (fp.windows || []).forEach(w => { w.position = w.position.map(snap); });

      // Clamp & deduplicate objects
      fp.objects = fp.objects.filter(o => {
        const [cx, cy] = o.center;
        const ok = cx > min_x && cx < max_x && cy > min_y && cy < max_y;
        if (!ok) console.log(`[Claude FP] Dropped OOB object: ${o.class} at ${o.center}`);
        return ok;
      });
      fp.objects.forEach(o => {
        o.center = o.center.map(snap);
        o.scale  = (o.scale || [0.6, 0.6]).map(s => Math.max(0.15, s));
      });
      // Remove duplicate objects (same class within 0.4m)
      const dedupedObjs = [];
      for (const o of fp.objects) {
        const dup = dedupedObjs.some(e =>
          e.class === o.class &&
          Math.hypot(e.center[0]-o.center[0], e.center[1]-o.center[1]) < 0.4
        );
        if (!dup) dedupedObjs.push(o);
      }
      fp.objects = dedupedObjs;

      // Filter and deduplicate doors
      if (fp.doors) {
        fp.doors = fp.doors.filter(d => d.width <= 1.0);
        const deduped = [];
        for (const d of fp.doors) {
          const dup = deduped.some(e =>
            Math.hypot(e.position[0]-d.position[0], e.position[1]-d.position[1]) < 1.5
          );
          if (!dup) deduped.push(d);
        }
        fp.doors = deduped;
      }

      // Save as latest
      const fs = require('fs'), path = require('path');
      fs.writeFileSync(path.join(__dirname, 'floor_plan.json'), JSON.stringify(fp, null, 2));
      console.log(`[Claude FP] Done: ${fp.walls?.length} walls, ${fp.objects?.length} objects, ${fp.doors?.length} doors`);

      res.json(fp);
    } catch (e) {
      console.error('[Claude FP] Error:', e.message);
      res.status(500).json({ error: e.message });
    }
  });

  // ── Save floor plan JSON (for user corrections) ───────────────────────────────
  app.post('/floorplan/save', express.json({ limit: '10mb' }), (req, res) => {
    const fs = require('fs'), path = require('path');
    fs.writeFileSync(path.join(__dirname, 'floor_plan.json'), JSON.stringify(req.body, null, 2));
    res.json({ ok: true });
  });

  app.listen(3001, () => {
    console.log('Proxy running on http://localhost:3001');
    console.log('API key set:', !!RUNPOD_API_KEY);
  });                                         
