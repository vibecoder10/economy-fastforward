import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '5050', 10);

// --- Node version check ---
const [major] = process.versions.node.split('.').map(Number);
if (major < 18) {
  console.error(`\n  Rubric Agents requires Node.js 18+. You are running ${process.version}.\n`);
  process.exit(1);
}

// --- Config ---
const CONFIG_PATH = path.join(__dirname, 'config.json');

function loadConfig() {
  try {
    return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
  } catch (e) {
    if (e.code !== 'ENOENT') console.warn(`  Warning: config.json parse error (${e.message}). Using defaults.`);
    return { brandName: 'RUBRIC Agents', agents: [] };
  }
}

// --- Icon Library (20 icons from Rubric Icons) ---
const ICON_LIBRARY = {
  "Robo":     [[0,0,1,0],[1,1,1,1],[1,1,1,1],[1,0,1,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]],
  "Crown":    [[1,0,1,0],[1,0,1,1],[1,1,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,1],[0,1,0,1],[0,0,0,0]],
  "Sentinel": [[0,1,1,0],[1,1,1,1],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,0],[0,1,1,0],[1,0,0,1]],
  "Fortress": [[1,0,0,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,1,0],[0,0,0,0]],
  "Phantom":  [[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,1,1,1],[0,1,0,0],[1,0,0,0]],
  "Spark":    [[0,0,0,1],[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,0],[0,1,0,0],[0,0,0,0]],
  "Apex":     [[0,0,1,0],[0,1,1,0],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,1,0],[0,0,0,0]],
  "Drift":    [[0,0,0,0],[0,1,0,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,1],[0,0,0,0]],
  "Halo":     [[0,1,1,1],[1,0,0,0],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]],
  "Orb":      [[0,0,1,1],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,0,1,1],[0,0,0,0]],
  "Rune":     [[1,0,1,0],[0,1,1,1],[0,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,1],[1,0,1,0],[0,0,0,0]],
  "Nova":     [[0,0,1,0],[0,1,0,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,0,1,0],[0,0,1,0],[0,0,0,0]],
  "Blade":    [[0,0,0,1],[0,0,1,1],[0,1,1,1],[0,1,0,1],[1,1,1,1],[1,1,1,0],[1,0,0,0],[0,0,0,0]],
  "Thorn":    [[1,0,0,0],[1,1,0,0],[1,1,1,1],[0,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,0],[0,0,0,0]],
  "Titan":    [[1,1,0,0],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]],
  "Warden":   [[0,1,0,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]],
  "Echo":     [[0,0,0,1],[0,1,1,1],[1,1,1,0],[1,1,0,1],[1,1,1,0],[0,1,1,1],[0,0,0,1],[0,0,0,0]],
  "Aegis":    [[0,0,1,0],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,0,1,0],[0,0,1,0]],
  "Beacon":   [[0,0,1,0],[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]],
  "Vertex":   [[0,0,1,0],[0,1,1,0],[1,1,1,1],[0,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,0],[0,0,0,0]],
};

// --- In-memory status store ---
const agentStatus = {};
const IDLE_MS = 5 * 60 * 1000;

// --- MIME ---
const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
};

function sendJSON(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function readBody(req) {
  return new Promise((resolve) => {
    let body = '';
    req.on('data', chunk => body += chunk);
    req.on('end', () => resolve(body));
  });
}

// --- Resolve pixels for an agent from config ---
function resolvePixels(agent) {
  if (agent.pixels) return agent.pixels;
  if (agent.icon && ICON_LIBRARY[agent.icon]) return ICON_LIBRARY[agent.icon];
  return ICON_LIBRARY['Robo'];
}

// --- HTTP Server ---
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  // --- Static: index.html ---
  if (pathname === '/' || pathname === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(fs.readFileSync(path.join(__dirname, 'index.html')));
    return;
  }

  // --- Static: icons.html ---
  if (pathname === '/icons.html') {
    const iconsPath = path.join(__dirname, 'icons.html');
    if (fs.existsSync(iconsPath)) {
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(fs.readFileSync(iconsPath));
    } else {
      res.writeHead(404);
      res.end('Not found');
    }
    return;
  }

  // --- API: Config (with resolved pixels) ---
  if (pathname === '/api/config' && req.method === 'GET') {
    const config = loadConfig();
    const agents = (config.agents || []).map(a => ({
      ...a,
      pixels: resolvePixels(a),
    }));
    sendJSON(res, { ...config, agents });
    return;
  }

  // --- API: Agent Status ---
  if (pathname === '/api/agent-status' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const config = loadConfig();
    const agents = config.agents || [];
    const now = Date.now();

    // Update mode
    if (body.agent && body.status) {
      agentStatus[body.agent] = {
        status: body.status,
        task: body.task || '',
        updatedAt: now
      };
      sendJSON(res, { success: true });
      return;
    }

    // Query mode — return status for all configured agents
    const statuses = agents.map(a => {
      const s = agentStatus[a.id] || {};
      const updatedAt = s.updatedAt || 0;
      const ageMs = updatedAt > 0 ? (now - updatedAt) : Infinity;
      const ageMin = updatedAt > 0 ? Math.floor((now - updatedAt) / 60000) : null;
      let status = s.status || 'idle';
      if (status === 'idle' && updatedAt > 0 && ageMs < IDLE_MS) status = 'recent';
      return {
        id: a.id,
        name: a.name || a.id,
        status,
        lastUpdate: updatedAt,
        ageMin,
        lastTask: s.task || '',
      };
    });
    sendJSON(res, { agents: statuses, timestamp: now });
    return;
  }

  // --- 404 ---
  res.writeHead(404);
  res.end('Not found');
});

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    console.error(`\n  Port ${PORT} is already in use.\n  Set a different port: PORT=5091 node server.js\n`);
    process.exit(1);
  }
  throw e;
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`\n  Rubric Agents`);
  console.log(`  http://localhost:${PORT}\n`);
});
