import 'dotenv/config';
import { createServer } from 'node:http';
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { join, extname, resolve, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { WebSocketServer } from 'ws';
import { createSign } from 'node:crypto';

const __dirname = fileURLToPath(new URL('.', import.meta.url));
const PORT = process.env.PORT || 5050;

// GitHub App config for token generation
const GH_APP_ID = process.env.GH_APP_ID || '';
const GH_PEM_PATH = process.env.GH_PEM_PATH || '';
const GH_INSTALL_ID = process.env.GH_INSTALL_ID || '';
const GH_REPO = process.env.GH_REPO || 'robonuggets/rubric';
const GH_TEMPLATE_PATH = process.env.GH_TEMPLATE_PATH || 'templates/flows';

function base64url(buf) {
  return Buffer.from(buf).toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_');
}

function makeJWT(appId, pemKey) {
  const now = Math.floor(Date.now() / 1000);
  const header = base64url(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
  const payload = base64url(JSON.stringify({ iat: now - 60, exp: now + 600, iss: appId }));
  const sign = createSign('RSA-SHA256');
  sign.update(header + '.' + payload);
  const sig = base64url(sign.sign(pemKey));
  return header + '.' + payload + '.' + sig;
}

async function generateInstallToken() {
  if (!GH_APP_ID || !GH_PEM_PATH || !GH_INSTALL_ID) return null;
  const pem = readFileSync(GH_PEM_PATH, 'utf8');
  const jwt = makeJWT(GH_APP_ID, pem);
  const resp = await fetch(`https://api.github.com/app/installations/${GH_INSTALL_ID}/access_tokens`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${jwt}`, 'Accept': 'application/vnd.github+json' }
  });
  const data = await resp.json();
  return data.token;
}

// Live workflow run state (for late-joining browsers)
let wfRunState = null;

const MIME = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.png': 'image/png',
  '.svg': 'image/svg+xml',
};

function sendJSON(res, data, status = 200) {
  const body = JSON.stringify(data);
  res.writeHead(status, { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(body) });
  res.end(body);
}

function wfBroadcast(data) {
  const msg = JSON.stringify(data);
  wss.clients.forEach(c => { if (c.readyState === 1) c.send(msg); });
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  // CORS for local dev (mockup pages calling the API)
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  try {
    // --- API routes ---

    // GET /api/workflows
    if (pathname === '/api/workflows' && req.method === 'GET') {
      try {
        const data = JSON.parse(readFileSync(join(__dirname, 'data', 'workflows.json'), 'utf8'));
        sendJSON(res, data);
      } catch (e) { sendJSON(res, []); }
      return;
    }

    // PUT /api/workflows/:id
    if (pathname.startsWith('/api/workflows/') && req.method === 'PUT') {
      const id = pathname.replace('/api/workflows/', '');
      let body = '';
      req.on('data', chunk => body += chunk);
      req.on('end', () => {
        try {
          const filePath = join(__dirname, 'data', 'workflows.json');
          const workflows = JSON.parse(readFileSync(filePath, 'utf8'));
          const idx = workflows.findIndex(w => w.id === id);
          const updated = JSON.parse(body);
          if (idx >= 0) workflows[idx] = updated;
          else workflows.push(updated);
          writeFileSync(filePath, JSON.stringify(workflows, null, 2));
          sendJSON(res, updated);
        } catch (e) { sendJSON(res, { error: e.message }, 500); }
      });
      return;
    }

    // GET /api/skill-content?path=...
    if (pathname === '/api/skill-content' && req.method === 'GET') {
      const skillPath = url.searchParams.get('path');
      if (!skillPath || !skillPath.endsWith('.md')) {
        sendJSON(res, { error: 'Invalid skill path' }, 400);
        return;
      }
      // Path traversal protection
      if (skillPath.includes('..')) {
        sendJSON(res, { error: 'Invalid path' }, 400);
        return;
      }
      const resolved = resolve(join(__dirname, skillPath));
      const base = resolve(__dirname);
      if (!resolved.startsWith(base)) {
        sendJSON(res, { error: 'Invalid path' }, 400);
        return;
      }
      try {
        const content = readFileSync(resolved, 'utf8');
        sendJSON(res, { content });
      } catch (e) {
        sendJSON(res, { error: 'File not found' }, 404);
      }
      return;
    }

    // POST /api/workflow-events (for agents to send events via HTTP)
    if (pathname === '/api/workflow-events' && req.method === 'POST') {
      let body = '';
      req.on('data', chunk => body += chunk);
      req.on('end', () => {
        try {
          const evt = JSON.parse(body);
          switch (evt.event) {
            case 'workflow:start':
              wfRunState = { workflowId: evt.workflowId, status: 'running', currentStep: -1, litSteps: [], actions: [], startedAt: Date.now() };
              wfBroadcast({ type: 'workflow:start', workflowId: evt.workflowId });
              break;
            case 'step:start':
              if (wfRunState) { wfRunState.currentStep = evt.stepIndex; wfRunState.actions = []; }
              wfBroadcast({ type: 'step:start', stepIndex: evt.stepIndex, skillId: evt.skillId });
              break;
            case 'step:action':
              if (wfRunState) wfRunState.actions.push(evt.text);
              wfBroadcast({ type: 'step:action', stepIndex: evt.stepIndex, text: evt.text });
              break;
            case 'step:complete':
              if (wfRunState) wfRunState.litSteps.push(evt.stepIndex);
              wfBroadcast({ type: 'step:complete', stepIndex: evt.stepIndex });
              break;
            case 'step:warn':
              wfBroadcast({ type: 'step:warn', stepIndex: evt.stepIndex, text: evt.text || 'Warning' });
              break;
            case 'step:error':
              if (wfRunState) { wfRunState.errorSteps = wfRunState.errorSteps || []; wfRunState.errorSteps.push(evt.stepIndex); }
              wfBroadcast({ type: 'step:error', stepIndex: evt.stepIndex, text: evt.text || 'Step failed' });
              break;
            case 'workflow:complete':
              if (wfRunState) wfRunState.status = 'done';
              wfBroadcast({ type: 'workflow:complete', workflowId: evt.workflowId });
              break;
            case 'workflow:reset':
              wfRunState = null;
              wfBroadcast({ type: 'workflow:reset' });
              break;
          }
          sendJSON(res, { ok: true });
        } catch (e) { sendJSON(res, { error: e.message }, 400); }
      });
      return;
    }

    // GET /api/install-prompt — generates a fresh token and returns the install prompt
    if (pathname === '/api/install-prompt' && req.method === 'GET') {
      try {
        const token = await generateInstallToken();
        if (!token) {
          sendJSON(res, { error: 'GitHub App not configured. Set GH_APP_ID, GH_PEM_PATH, and GH_INSTALL_ID in .env' }, 500);
          return;
        }
        const prompt = `Clone the Rubric Flows template and set it up locally. Run these commands:

git clone https://x-access-token:${token}@github.com/${GH_REPO}.git rubric-temp
mkdir -p rubric-flows
cp -r rubric-temp/${GH_TEMPLATE_PATH}/* rubric-flows/
rm -rf rubric-temp
cd rubric-flows
npm install
node server.js

The server will start at http://localhost:5050. Open it in a browser to see the workflow visualizer.

To add your own workflows, edit data/workflows.json. See the README.md for the full schema and instructions.`;

        sendJSON(res, { prompt, expiresIn: '1 hour' });
      } catch (e) {
        sendJSON(res, { error: e.message }, 500);
      }
      return;
    }

    // GET /api/workflow-state
    if (pathname === '/api/workflow-state' && req.method === 'GET') {
      sendJSON(res, wfRunState || { status: 'idle' });
      return;
    }

    // --- Static file serving ---
    let filePath = join(__dirname, pathname === '/' ? 'index.html' : pathname);
    filePath = normalize(filePath);

    // Ensure we don't serve files outside our directory
    if (!filePath.startsWith(resolve(__dirname))) {
      res.writeHead(403);
      res.end('Forbidden');
      return;
    }

    if (!existsSync(filePath)) {
      res.writeHead(404);
      res.end('Not found');
      return;
    }

    const ext = extname(filePath);
    const mime = MIME[ext] || 'application/octet-stream';
    const content = readFileSync(filePath);
    res.writeHead(200, { 'Content-Type': mime });
    res.end(content);

  } catch (e) {
    console.error('Request error:', e);
    res.writeHead(500);
    res.end('Internal server error');
  }
});

// WebSocket server on the same HTTP server
const wss = new WebSocketServer({ server });
wss.on('connection', (ws) => {
  // Send current state on connect (catch-up for late joiners)
  if (wfRunState) {
    ws.send(JSON.stringify({ type: 'state:sync', state: wfRunState }));
  }
  // Also accept WS messages from agents directly
  ws.on('message', (raw) => {
    try {
      const msg = JSON.parse(raw);
      // Forward as broadcast event (same handling as HTTP POST)
      switch (msg.type) {
        case 'workflow:start':
          wfRunState = { workflowId: msg.workflowId, status: 'running', currentStep: -1, litSteps: [], actions: [], startedAt: Date.now() };
          wfBroadcast({ type: 'workflow:start', workflowId: msg.workflowId });
          break;
        case 'step:start':
          if (wfRunState) { wfRunState.currentStep = msg.stepIndex; wfRunState.actions = []; }
          wfBroadcast({ type: 'step:start', stepIndex: msg.stepIndex });
          break;
        case 'step:action':
          if (wfRunState) wfRunState.actions.push(msg.text);
          wfBroadcast({ type: 'step:action', text: msg.text });
          break;
        case 'step:complete':
          if (wfRunState) wfRunState.litSteps.push(msg.stepIndex);
          wfBroadcast({ type: 'step:complete', stepIndex: msg.stepIndex });
          break;
        case 'step:warn':
          wfBroadcast({ type: 'step:warn', stepIndex: msg.stepIndex, text: msg.text || 'Warning' });
          break;
        case 'step:error':
          if (wfRunState) { wfRunState.errorSteps = wfRunState.errorSteps || []; wfRunState.errorSteps.push(msg.stepIndex); }
          wfBroadcast({ type: 'step:error', stepIndex: msg.stepIndex, text: msg.text || 'Step failed' });
          break;
        case 'workflow:complete':
          if (wfRunState) wfRunState.status = 'done';
          wfBroadcast({ type: 'workflow:complete', workflowId: msg.workflowId });
          break;
        case 'workflow:reset':
          wfRunState = null;
          wfBroadcast({ type: 'workflow:reset' });
          break;
      }
    } catch (e) { /* ignore malformed messages */ }
  });
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`Rubric Flows running at http://127.0.0.1:${PORT}`);
});
