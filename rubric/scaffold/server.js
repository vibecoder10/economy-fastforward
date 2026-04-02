import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '5050', 10);
const DATA_DIR = path.join(__dirname, 'data');

// --- Node version check ---
const [major] = process.versions.node.split('.').map(Number);
if (major < 18) {
  console.error(`\n  Rubric Console requires Node.js 18+. You are running ${process.version}.\n`);
  process.exit(1);
}

// Ensure data dir exists
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

// --- Template detection ---
const TEMPLATE_CHECKS = {
  agents:        path.join(__dirname, '../agents/index.html'),
  flows:         path.join(__dirname, '../flows/server.js'),
  'skill-trees': path.join(__dirname, '../skill-trees/server.js'),
  crons:         path.join(__dirname, '../crons/server.js'),
  team:          path.join(__dirname, '../team/server.js'),
};

const INSTALLED = [];

for (const [name, checkPath] of Object.entries(TEMPLATE_CHECKS)) {
  if (fs.existsSync(checkPath)) {
    INSTALLED.push(name);
    console.log(`  Template detected: ${name}`);
  }
}

// Enforce tab order — welcome and icons are always present (part of scaffold)
const TAB_ORDER = ['welcome', 'agents', 'flows', 'skill-trees', 'crons', 'team', 'icons'];
const INSTALLED_TABS = ['welcome', ...INSTALLED, 'icons']
  .filter((v, i, a) => a.indexOf(v) === i)
  .sort((a, b) => {
    const ai = TAB_ORDER.indexOf(a);
    const bi = TAB_ORDER.indexOf(b);
    return (ai === -1 ? 999 : ai) - (bi === -1 ? 999 : bi);
  });

// ============================================================
// FLOWS — state and helpers (only loaded if flows is installed)
// ============================================================
let wfRunState = null;

function wfBroadcast(data) {
  if (!wss) return;
  const msg = JSON.stringify(data);
  wss.clients.forEach(c => { if (c.readyState === 1) c.send(msg); });
}

// ============================================================
// SKILL-TREES — scan logic (mirrored from skill-trees/server.js)
// ============================================================
const SKILL_TREE_ROOT = process.env.SKILL_TREE_ROOT
  ? path.resolve(process.env.SKILL_TREE_ROOT)
  : path.resolve(__dirname, '../skill-trees/example-workspace');

const ST_ICON_LIBRARY = {
  "Robo":     { c: "#ffffff", p: [[0,0,1,0],[1,1,1,1],[1,1,1,1],[1,0,1,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]] },
  "Crown":    { c: "#e8c547", p: [[1,0,1,0],[1,0,1,1],[1,1,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Sentinel": { c: "#ff2d55", p: [[0,1,1,0],[1,1,1,1],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,0],[0,1,1,0],[1,0,0,1]] },
  "Fortress": { c: "#ff9500", p: [[1,0,0,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,1,0],[0,0,0,0]] },
  "Phantom":  { c: "#af52de", p: [[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,1,1,1],[0,1,0,0],[1,0,0,0]] },
  "Spark":    { c: "#30d158", p: [[0,0,0,1],[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,0],[0,1,0,0],[0,0,0,0]] },
  "Apex":     { c: "#ff3b30", p: [[0,0,1,0],[0,1,1,0],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,1,0],[0,0,0,0]] },
  "Drift":    { c: "#5ac8fa", p: [[0,0,0,0],[0,1,0,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,1],[0,0,0,0]] },
  "Halo":     { c: "#ffd60a", p: [[0,1,1,1],[1,0,0,0],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Orb":      { c: "#34c759", p: [[0,0,1,1],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,0,1,1],[0,0,0,0]] },
  "Rune":     { c: "#5e5ce6", p: [[1,0,1,0],[0,1,1,1],[0,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,1],[1,0,1,0],[0,0,0,0]] },
  "Nova":     { c: "#ffcc02", p: [[0,0,1,0],[0,1,0,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,0,1,0],[0,0,1,0],[0,0,0,0]] },
  "Sage":     { c: "#00c7be", p: [[0,0,1,0],[0,1,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,1,0,0],[0,0,0,0]] },
  "Warden":   { c: "#2ecc71", p: [[0,1,0,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Echo":     { c: "#007aff", p: [[0,0,0,1],[0,1,1,1],[1,1,1,0],[1,1,0,1],[1,1,1,0],[0,1,1,1],[0,0,0,1],[0,0,0,0]] },
};

const ST_PALETTE = ['#58abf5','#f5a623','#b47aff','#50e3c2','#ff6b6b','#ffd60a','#30d158','#ff2d55'];

function stIsDir(p) { try { return fs.statSync(p).isDirectory(); } catch { return false; } }
function stFileExists(p) { try { return fs.statSync(p).isFile(); } catch { return false; } }

function stScanSkillDir(skillsDir) {
  const skills = [];
  if (!stIsDir(skillsDir)) return skills;
  for (const entry of fs.readdirSync(skillsDir)) {
    if (entry.startsWith('.')) continue;
    const entryPath = path.join(skillsDir, entry);
    if (!stIsDir(entryPath)) continue;
    const skillFile = path.join(entryPath, 'SKILL.md');
    if (!stFileExists(skillFile)) continue;
    const raw = fs.readFileSync(skillFile, 'utf8');
    let name = entry, description = '';
    const fmMatch = raw.match(/^---\n([\s\S]*?)\n---/);
    if (fmMatch) {
      const nM = fmMatch[1].match(/^name:\s*(.+)$/m);
      const dM = fmMatch[1].match(/^description:\s*(.+)$/m);
      if (nM) name = nM[1].trim();
      if (dM) description = dM[1].trim();
    }
    if (!description) {
      for (const line of raw.split('\n')) {
        if (line.startsWith('#') || line.startsWith('---') || !line.trim()) continue;
        description = line.trim().slice(0, 200);
        break;
      }
    }
    const size = fs.statSync(skillFile).size;
    skills.push({ id: entry, name, description, size, dir: skillsDir });
  }
  return skills;
}

function stDetectSkillDirs(workspace) {
  const dirs = [];
  const cc = path.join(workspace, '.claude', 'skills');
  if (stIsDir(cc)) dirs.push({ path: cc, platform: 'claude-code' });
  const oc = path.join(workspace, 'skills');
  if (stIsDir(oc)) dirs.push({ path: oc, platform: 'openclaw' });
  const ag = path.join(workspace, '.agent', 'skills');
  if (stIsDir(ag)) dirs.push({ path: ag, platform: 'antigravity' });
  return dirs;
}

function stDetectAgentWorkspaces(root) {
  const workspaces = [];
  const rootDirs = stDetectSkillDirs(root);
  if (rootDirs.length > 0) workspaces.push({ path: root, skillDirs: rootDirs, isRoot: true });
  const agentsDir = path.join(root, 'agents');
  if (stIsDir(agentsDir)) {
    for (const entry of fs.readdirSync(agentsDir)) {
      const agentPath = path.join(agentsDir, entry);
      if (!stIsDir(agentPath)) continue;
      const dirs = stDetectSkillDirs(agentPath);
      if (dirs.length > 0) workspaces.push({ path: agentPath, skillDirs: dirs, isRoot: false, dirName: entry });
    }
  }
  for (const entry of fs.readdirSync(root)) {
    if (entry === 'agents' || entry === 'node_modules' || entry.startsWith('.')) continue;
    const subPath = path.join(root, entry);
    if (!stIsDir(subPath)) continue;
    const dirs = stDetectSkillDirs(subPath);
    if (dirs.length > 0 && !workspaces.some(w => w.path === subPath)) {
      workspaces.push({ path: subPath, skillDirs: dirs, isRoot: false, dirName: entry });
    }
  }
  return workspaces;
}

function stBuildSkillTree() {
  let cfgAgents = [], cfgSkillDirs = [];
  const cfgPath = path.join(__dirname, '../skill-trees/config.json');
  if (stFileExists(cfgPath)) {
    try {
      const cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
      cfgAgents = cfg.agents || [];
      cfgSkillDirs = cfg.skillDirs || [];
    } catch {}
  }

  const agents = [];
  const skillMap = {};
  let colorIdx = 0;
  const nextColor = () => ST_PALETTE[colorIdx++ % ST_PALETTE.length];

  const workspaces = stDetectAgentWorkspaces(SKILL_TREE_ROOT);

  for (const ws of workspaces) {
    if (ws.isRoot) continue;
    const dirName = ws.dirName || path.basename(ws.path);
    const agentId = dirName.toLowerCase();
    const cfgAgent = cfgAgents.find(a => a.id === agentId || a.id === dirName);
    let displayName = cfgAgent?.name || dirName;
    let role = '';
    if (!cfgAgent?.name) {
      for (const docFile of ['IDENTITY.md', 'CLAUDE.md']) {
        try {
          const doc = fs.readFileSync(path.join(ws.path, docFile), 'utf8');
          const nameMatch = doc.match(/\*\*Name:\*\*\s*(.+)/);
          const roleMatch = doc.match(/\*\*Role:\*\*\s*(.+)/);
          if (nameMatch) displayName = nameMatch[1].trim();
          if (roleMatch) role = roleMatch[1].trim();
          if (nameMatch) break;
        } catch {}
      }
    }
    const color = cfgAgent?.color || nextColor();
    const icon = cfgAgent?.icon || 'Robo';
    const agentSkillIds = [];
    for (const sd of ws.skillDirs) {
      const skills = stScanSkillDir(sd.path);
      for (const s of skills) {
        agentSkillIds.push(s.id);
        if (!skillMap[s.id]) skillMap[s.id] = { ...s, agents: [] };
        if (!skillMap[s.id].agents.includes(agentId)) skillMap[s.id].agents.push(agentId);
      }
    }
    agents.push({ id: agentId, name: displayName, color, icon, role, workspace: ws.path, skills: agentSkillIds, customPixels: cfgAgent?.pixels || null });
  }

  const rootWs = workspaces.find(w => w.isRoot);
  if (rootWs) {
    const allAgentIds = agents.map(a => a.id);
    for (const sd of rootWs.skillDirs) {
      const skills = stScanSkillDir(sd.path);
      for (const s of skills) {
        if (!skillMap[s.id]) { skillMap[s.id] = { ...s, agents: [...allAgentIds], shared: true }; }
        else { for (const aid of allAgentIds) { if (!skillMap[s.id].agents.includes(aid)) skillMap[s.id].agents.push(aid); } skillMap[s.id].shared = true; }
        for (const agent of agents) { if (!agent.skills.includes(s.id)) agent.skills.push(s.id); }
      }
    }
  }

  for (const dir of cfgSkillDirs) {
    const resolved = path.resolve(SKILL_TREE_ROOT, dir);
    if (!stIsDir(resolved)) continue;
    const skills = stScanSkillDir(resolved);
    const allAgentIds = agents.map(a => a.id);
    for (const s of skills) { if (!skillMap[s.id]) skillMap[s.id] = { ...s, agents: [...allAgentIds], shared: true }; }
  }

  if (agents.length === 0 && Object.keys(skillMap).length > 0) {
    agents.push({ id: 'workspace', name: 'Workspace', color: ST_PALETTE[0], icon: 'Robo', role: '', workspace: SKILL_TREE_ROOT, skills: Object.keys(skillMap), customPixels: null });
    for (const s of Object.values(skillMap)) { if (s.agents.length === 0) s.agents.push('workspace'); }
  }

  return { agents, skills: Object.values(skillMap) };
}

function stGetAllSkillDirs() {
  const dirs = new Set();
  const cfgPath = path.join(__dirname, '../skill-trees/config.json');
  let cfgSkillDirs = [];
  if (stFileExists(cfgPath)) {
    try { cfgSkillDirs = (JSON.parse(fs.readFileSync(cfgPath, 'utf8')).skillDirs) || []; } catch {}
  }
  const workspaces = stDetectAgentWorkspaces(SKILL_TREE_ROOT);
  for (const ws of workspaces) { for (const sd of ws.skillDirs) dirs.add(sd.path); }
  for (const dir of cfgSkillDirs) { const r = path.resolve(SKILL_TREE_ROOT, dir); if (stIsDir(r)) dirs.add(r); }
  return [...dirs];
}

// ============================================================
// TEAM — scan logic (mirrored from team/server.js)
// ============================================================
const TEAM_DIR = path.join(__dirname, '../team');

function teamLoadConfig() {
  try { return JSON.parse(fs.readFileSync(path.join(TEAM_DIR, 'config.json'), 'utf8')); }
  catch { return null; }
}

function teamScanSkills(basePath) {
  const skills = [];
  if (!fs.existsSync(basePath)) return skills;
  function walk(dir) {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (fs.existsSync(path.join(fullPath, 'SKILL.md'))) skills.push(entry.name);
        walk(fullPath);
      }
    }
  }
  walk(basePath);
  return skills;
}

function teamGetSkills(config) {
  if (!config) return {};
  const skillsRoot = path.resolve(TEAM_DIR, config.skillsRoot || '../');
  const result = {};
  const sharedPath = path.join(skillsRoot, '.claude', 'skills');
  const sharedSkills = teamScanSkills(sharedPath);
  result[config.lead.id] = [...sharedSkills];
  for (const agent of (config.agents || [])) {
    const agentPath = path.join(skillsRoot, 'agents', agent.id.toUpperCase(), '.claude', 'skills');
    const agentSkills = teamScanSkills(agentPath);
    result[agent.id] = [...sharedSkills, ...agentSkills];
  }
  return result;
}

// ============================================================
// CRONS — load logic (mirrored from crons/server.js)
// ============================================================
const CRONS_DIR = path.join(__dirname, '../crons');

function cronsLoadConfig() {
  const configPath = path.join(CRONS_DIR, 'config.json');
  if (fs.existsSync(configPath)) {
    try { return JSON.parse(fs.readFileSync(configPath, 'utf8')); } catch {}
  }
  return { cronPaths: ['./data/crons.json'], timezone: 'auto' };
}

function loadCrons() {
  const config = cronsLoadConfig();
  const allJobs = [];
  const paths = config.cronPaths || ['./data/crons.json'];
  for (const p of paths) {
    const fullPath = (p.startsWith('/') || p.match(/^[A-Z]:\\/))
      ? p
      : path.join(CRONS_DIR, p);
    if (!fs.existsSync(fullPath)) continue;
    try {
      const raw = JSON.parse(fs.readFileSync(fullPath, 'utf8'));
      let jobsArr;
      if (Array.isArray(raw)) jobsArr = raw;
      else if (raw.jobs) jobsArr = raw.jobs;
      else if (raw.crons) jobsArr = raw.crons;
      else continue;
      for (let i = 0; i < jobsArr.length; i++) {
        const j = jobsArr[i];
        let expr, tz;
        if (typeof j.schedule === 'string') { expr = j.schedule; tz = j.tz || config.timezone || 'auto'; }
        else if (j.schedule && j.schedule.expr) { expr = j.schedule.expr; tz = j.schedule.tz || config.timezone || 'auto'; }
        else if (j.cron) { expr = j.cron; tz = j.tz || config.timezone || 'auto'; }
        else continue;
        allJobs.push({
          id: j.id || j.name || `cron-${i}`,
          name: j.name || j.desc || 'unnamed',
          enabled: j.enabled !== false,
          schedule: { expr, tz },
          description: j.description || j.desc || j.prompt || '',
          agent: j.agent || null,
          sessionTarget: j.type || 'session',
          delivery: j.delivery || null,
          state: j.state || null,
        });
      }
    } catch (err) { console.error(`Failed to read cron file ${fullPath}:`, err.message); }
  }
  return allJobs;
}

// ============================================================
// FLOWS — workflow data loader
// ============================================================
const FLOWS_DIR = path.join(__dirname, '../flows');

function loadWorkflows() {
  try { return JSON.parse(fs.readFileSync(path.join(FLOWS_DIR, 'data', 'workflows.json'), 'utf8')); }
  catch { return []; }
}

// ============================================================
// SCAFFOLD — Config, Status, Prefs
// ============================================================
const CONFIG_PATH = path.join(__dirname, 'config.json');

function loadConfig() {
  try { return JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8')); }
  catch (e) {
    if (e.code !== 'ENOENT') console.warn(`  Warning: config.json parse error (${e.message}). Using defaults.`);
    return {};
  }
}

function resolvePixels(agent) {
  if (agent.pixels) return agent.pixels;
  if (agent.icon && ST_ICON_LIBRARY[agent.icon]) return ST_ICON_LIBRARY[agent.icon].p;
  return ST_ICON_LIBRARY['Robo'].p;
}

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

const STATUS_FILE = path.join(DATA_DIR, 'agent-status.json');
const IDLE_MS = 5 * 60 * 1000;

function readStatus() {
  try { return JSON.parse(fs.readFileSync(STATUS_FILE, 'utf8')); } catch { return {}; }
}

function writeStatus(data) {
  fs.writeFileSync(STATUS_FILE, JSON.stringify(data, null, 2));
}

const PREFS_FILE = path.join(DATA_DIR, 'ui-prefs.json');

function readPrefs() {
  try { return JSON.parse(fs.readFileSync(PREFS_FILE, 'utf8')); } catch { return {}; }
}

function writePrefs(data) {
  fs.writeFileSync(PREFS_FILE, JSON.stringify(data, null, 2));
}

// ============================================================
// HTTP SERVER
// ============================================================
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, PUT, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  // --- Static: serve index.html ---
  if (pathname === '/' || pathname === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(fs.readFileSync(path.join(__dirname, 'index.html')));
    return;
  }

  // ===== SCAFFOLD ROUTES =====

  // GET /api/tabs — return installed template tabs
  if (pathname === '/api/tabs' && req.method === 'GET') {
    sendJSON(res, INSTALLED_TABS);
    return;
  }

  // GET /api/config
  if (pathname === '/api/config' && req.method === 'GET') {
    const config = loadConfig();
    if (config.agents) {
      config.agents = config.agents.map(a => ({ ...a, pixels: resolvePixels(a) }));
    }
    sendJSON(res, config);
    return;
  }

  // POST /api/agent-status (query or update)
  if (pathname === '/api/agent-status' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const config = loadConfig();
    const agents = config.agents || [];
    const now = Date.now();
    let statusData = readStatus();
    if (body.agent && body.status) {
      statusData[body.agent] = { status: body.status, task: body.task || '', updatedAt: now };
      writeStatus(statusData);
      sendJSON(res, { success: true });
      return;
    }
    const statuses = agents.map(a => {
      const s = statusData[a.id] || {};
      const updatedAt = s.updatedAt || 0;
      const ageMs = updatedAt > 0 ? (now - updatedAt) : Infinity;
      const ageMin = updatedAt > 0 ? Math.floor((now - updatedAt) / 60000) : null;
      let status = s.status || 'idle';
      if (status === 'idle' && updatedAt > 0 && ageMs < IDLE_MS) status = 'recent';
      return { id: a.id, name: a.name || a.id, status, lastUpdate: updatedAt, ageMin, lastTask: s.task || '' };
    });
    sendJSON(res, { agents: statuses, timestamp: now });
    return;
  }

  // GET /api/prefs
  if (pathname === '/api/prefs' && req.method === 'GET') {
    sendJSON(res, readPrefs());
    return;
  }

  // POST /api/prefs
  if (pathname === '/api/prefs' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const existing = readPrefs();
    Object.assign(existing, body);
    writePrefs(existing);
    sendJSON(res, { success: true });
    return;
  }

  // ===== FLOWS ROUTES =====
  if (INSTALLED.includes('flows')) {
    // GET /api/workflows
    if (pathname === '/api/workflows' && req.method === 'GET') {
      sendJSON(res, loadWorkflows());
      return;
    }

    // PUT /api/workflows/:id
    if (pathname.startsWith('/api/workflows/') && req.method === 'PUT') {
      const id = pathname.replace('/api/workflows/', '');
      const body = await readBody(req);
      try {
        const filePath = path.join(FLOWS_DIR, 'data', 'workflows.json');
        const workflows = JSON.parse(fs.readFileSync(filePath, 'utf8'));
        const idx = workflows.findIndex(w => w.id === id);
        const updated = JSON.parse(body);
        if (idx >= 0) workflows[idx] = updated;
        else workflows.push(updated);
        fs.writeFileSync(filePath, JSON.stringify(workflows, null, 2));
        sendJSON(res, updated);
      } catch (e) { sendJSON(res, { error: e.message }, 500); }
      return;
    }

    // POST /api/workflow-events
    if (pathname === '/api/workflow-events' && req.method === 'POST') {
      const body = await readBody(req);
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
      return;
    }

    // GET /api/workflow-state
    if (pathname === '/api/workflow-state' && req.method === 'GET') {
      sendJSON(res, wfRunState || { status: 'idle' });
      return;
    }

    // GET /api/skill-content?path=...
    if (pathname === '/api/skill-content' && req.method === 'GET') {
      const skillPath = url.searchParams.get('path');
      if (!skillPath || !skillPath.endsWith('.md') || skillPath.includes('..')) {
        sendJSON(res, { error: 'Invalid skill path' }, 400);
        return;
      }
      const resolved = path.resolve(path.join(FLOWS_DIR, skillPath));
      if (!resolved.startsWith(path.resolve(FLOWS_DIR))) {
        sendJSON(res, { error: 'Invalid path' }, 400);
        return;
      }
      try { sendJSON(res, { content: fs.readFileSync(resolved, 'utf8') }); }
      catch { sendJSON(res, { error: 'File not found' }, 404); }
      return;
    }
  }

  // ===== CRONS ROUTES =====
  if (INSTALLED.includes('crons')) {
    if (pathname === '/api/crons' && req.method === 'GET') {
      try { sendJSON(res, loadCrons()); }
      catch (err) { sendJSON(res, { error: 'Could not read cron jobs', message: err.message }, 500); }
      return;
    }
  }

  // ===== SKILL-TREES ROUTES =====
  if (INSTALLED.includes('skill-trees')) {
    if (pathname === '/api/skill-tree' && req.method === 'GET') {
      const data = stBuildSkillTree();
      data.iconLibrary = ST_ICON_LIBRARY;
      sendJSON(res, data);
      return;
    }

    if (pathname.startsWith('/api/skills/') && pathname.endsWith('/content') && req.method === 'GET') {
      const skillId = decodeURIComponent(pathname.replace('/api/skills/', '').replace('/content', ''));
      if (skillId.includes('..') || skillId.includes('/') || skillId.includes('\\')) {
        sendJSON(res, { error: 'Invalid skill ID' }, 400);
        return;
      }
      const dirs = stGetAllSkillDirs();
      for (const dir of dirs) {
        const skillFile = path.join(dir, skillId, 'SKILL.md');
        const resolved = path.resolve(skillFile);
        if (!resolved.startsWith(path.resolve(dir))) continue;
        if (stFileExists(resolved)) {
          sendJSON(res, { id: skillId, content: fs.readFileSync(resolved, 'utf8') });
          return;
        }
      }
      sendJSON(res, { error: 'Skill not found' }, 404);
      return;
    }

    if (pathname.startsWith('/api/agent-doc/') && req.method === 'GET') {
      const parts = pathname.replace('/api/agent-doc/', '').split('/');
      const agentId = decodeURIComponent(parts[0] || '');
      const docType = parts[1] || 'claude';
      if (!agentId || agentId.includes('..') || docType.includes('..')) {
        sendJSON(res, { error: 'Invalid path' }, 400);
        return;
      }
      const stCfgPath = path.join(__dirname, '../skill-trees/config.json');
      let stCfg = {};
      if (stFileExists(stCfgPath)) {
        try { stCfg = JSON.parse(fs.readFileSync(stCfgPath, 'utf8')); } catch {}
      }
      const docPaths = stCfg?.docPaths || { claude: 'CLAUDE.md', soul: 'SOUL.md' };
      const fileName = docPaths[docType];
      if (!fileName) { sendJSON(res, { error: 'Unknown doc type' }, 404); return; }
      const workspaces = stDetectAgentWorkspaces(SKILL_TREE_ROOT);
      const cfgAgent = (stCfg?.agents || []).find(a => a.id === agentId);
      let workspace = cfgAgent?.workspace ? path.resolve(SKILL_TREE_ROOT, cfgAgent.workspace) : null;
      if (!workspace) {
        const ws = workspaces.find(w => !w.isRoot && (w.dirName || path.basename(w.path)).toLowerCase() === agentId);
        if (ws) workspace = ws.path;
      }
      if (!workspace) { sendJSON(res, { error: 'Agent not found' }, 404); return; }
      const docPath = path.resolve(workspace, fileName);
      if (!docPath.startsWith(path.resolve(workspace))) { sendJSON(res, { error: 'Invalid path' }, 400); return; }
      try { sendJSON(res, { content: fs.readFileSync(docPath, 'utf8') }); }
      catch { sendJSON(res, { error: `${fileName} not found` }, 404); }
      return;
    }
  }

  // ===== TEAM ROUTES =====
  if (INSTALLED.includes('team')) {
    if (pathname === '/api/team' && req.method === 'GET') {
      const cfg = teamLoadConfig();
      if (!cfg) { sendJSON(res, { error: 'team/config.json not found' }, 404); return; }
      sendJSON(res, cfg);
      return;
    }

    if (pathname === '/api/team/skills' && req.method === 'GET') {
      const cfg = teamLoadConfig();
      sendJSON(res, teamGetSkills(cfg));
      return;
    }
  }

  // --- 404 ---
  res.writeHead(404);
  res.end('Not found');
});

// ============================================================
// WEBSOCKET (for flows live mode) — only if ws is available
// ============================================================
let wss = null;
try {
  const { WebSocketServer } = await import('ws');
  wss = new WebSocketServer({ server });
  wss.on('connection', (ws) => {
    // Catch-up for late joiners
    if (wfRunState) ws.send(JSON.stringify({ type: 'state:sync', state: wfRunState }));
    ws.on('message', (raw) => {
      try {
        const msg = JSON.parse(raw);
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
      } catch { /* ignore malformed */ }
    });
  });
} catch {
  console.warn('  ws package not found — WebSocket live mode unavailable. Run: npm install ws');
}

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    console.error(`\n  Port ${PORT} is already in use.\n  Set a different port: PORT=5051 node server.js\n`);
    process.exit(1);
  }
  throw e;
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`\n  Rubric Console`);
  console.log(`  http://localhost:${PORT}`);
  console.log(`  Templates active: ${INSTALLED_TABS.join(', ')}\n`);
});
