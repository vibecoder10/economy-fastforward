import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '5050', 10);
const PLATFORM = (process.env.PLATFORM || 'auto').toLowerCase();
const SKILL_TREE_ROOT = process.env.SKILL_TREE_ROOT
  ? path.resolve(process.env.SKILL_TREE_ROOT)
  : path.resolve(__dirname, 'example-workspace');

// --- Node version check ---
const [major] = process.versions.node.split('.').map(Number);
if (major < 18) {
  console.error(`\n  Skill Tree requires Node.js 18+. You are running ${process.version}.\n  Please upgrade: https://nodejs.org\n`);
  process.exit(1);
}

// --- Config ---
const CONFIG_PATH = path.join(__dirname, 'config.json');

function loadConfig() {
  try {
    const raw = fs.readFileSync(CONFIG_PATH, 'utf8');
    return JSON.parse(raw);
  } catch (e) {
    if (e.code !== 'ENOENT') {
      console.warn(`  Warning: config.json parse error (${e.message}). Using auto-scan only.`);
    }
    return null;
  }
}

function saveConfig(cfg) {
  fs.writeFileSync(CONFIG_PATH, JSON.stringify(cfg, null, 2));
}

// --- Icon Library (all 50 + Robo) ---
const ICON_LIBRARY = {
  "Robo":     { c: "#ffffff", p: [[0,0,1,0],[1,1,1,1],[1,1,1,1],[1,0,1,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]] },
  "Crown":    { c: "#e8c547", p: [[1,0,1,0],[1,0,1,1],[1,1,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Sentinel": { c: "#ff2d55", p: [[0,1,1,0],[1,1,1,1],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,0],[0,1,1,0],[1,0,0,1]] },
  "Fortress": { c: "#ff9500", p: [[1,0,0,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,1,0],[0,0,0,0]] },
  "Phantom":  { c: "#af52de", p: [[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,1,1,1],[0,1,0,0],[1,0,0,0]] },
  "Spark":    { c: "#30d158", p: [[0,0,0,1],[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,0],[0,1,0,0],[0,0,0,0]] },
  "Apex":     { c: "#ff3b30", p: [[0,0,1,0],[0,1,1,0],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,1,0],[0,0,0,0]] },
  "Drift":    { c: "#5ac8fa", p: [[0,0,0,0],[0,1,0,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,1],[0,0,0,0]] },
  "Halo":     { c: "#ffd60a", p: [[0,1,1,1],[1,0,0,0],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Claw":     { c: "#ff6723", p: [[1,0,0,0],[1,0,0,0],[1,1,1,1],[0,1,0,1],[0,1,1,1],[1,1,1,1],[1,0,0,0],[0,0,0,0]] },
  "Prism":    { c: "#64d2ff", p: [[0,0,1,0],[0,1,0,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,0],[0,0,0,0]] },
  "Fang":     { c: "#bf5af2", p: [[0,0,0,0],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,1,0,1],[0,0,0,0]] },
  "Orb":      { c: "#34c759", p: [[0,0,1,1],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,0,1,1],[0,0,0,0]] },
  "Pike":     { c: "#ff6482", p: [[0,0,1,0],[0,0,1,0],[0,1,1,1],[0,1,0,1],[1,1,1,1],[0,1,1,1],[0,1,1,0],[0,0,0,0]] },
  "Ember":    { c: "#ff453a", p: [[0,1,0,0],[1,1,1,0],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,0,1,1],[0,0,1,0],[0,0,0,0]] },
  "Rune":     { c: "#5e5ce6", p: [[1,0,1,0],[0,1,1,1],[0,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,1],[1,0,1,0],[0,0,0,0]] },
  "Sage":     { c: "#00c7be", p: [[0,0,1,0],[0,1,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,1,0,0],[0,0,0,0]] },
  "Nova":     { c: "#ffcc02", p: [[0,0,1,0],[0,1,0,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,0,1,0],[0,0,1,0],[0,0,0,0]] },
  "Blade":    { c: "#8e8e93", p: [[0,0,0,1],[0,0,1,1],[0,1,1,1],[0,1,0,1],[1,1,1,1],[1,1,1,0],[1,0,0,0],[0,0,0,0]] },
  "Mist":     { c: "#aeaeb2", p: [[0,1,1,0],[1,1,1,1],[0,1,1,1],[0,1,0,1],[0,1,1,1],[1,1,1,1],[0,1,1,0],[0,0,0,0]] },
  "Thorn":    { c: "#0a84ff", p: [[1,0,0,0],[1,1,0,0],[1,1,1,1],[0,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,0],[0,0,0,0]] },
  "Flare":    { c: "#ff375f", p: [[0,1,0,0],[0,1,1,0],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,0],[0,1,0,0],[0,0,0,0]] },
  "Pulse":    { c: "#da77f2", p: [[0,0,0,0],[0,0,1,1],[0,1,1,1],[1,1,0,1],[0,1,1,1],[0,0,1,0],[0,0,0,0],[0,0,0,0]] },
  "Titan":    { c: "#c41e3a", p: [[1,1,0,0],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]] },
  "Wisp":     { c: "#b4d455", p: [[0,0,1,0],[0,0,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,0],[0,0,1,1],[0,0,1,0],[0,0,0,0]] },
  "Shard":    { c: "#7b68ee", p: [[0,0,0,1],[0,0,1,1],[0,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,0],[0,0,0,1],[0,0,0,0]] },
  "Warden":   { c: "#2ecc71", p: [[0,1,0,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Echo":     { c: "#007aff", p: [[0,0,0,1],[0,1,1,1],[1,1,1,0],[1,1,0,1],[1,1,1,0],[0,1,1,1],[0,0,0,1],[0,0,0,0]] },
  "Fuse":     { c: "#ff2d92", p: [[0,0,0,0],[1,0,1,0],[1,1,1,1],[0,1,0,1],[1,1,1,1],[1,0,1,0],[0,0,0,0],[0,0,0,0]] },
  "Crux":     { c: "#eb2f06", p: [[0,1,0,0],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,0],[0,1,1,1],[0,1,0,0],[0,0,0,0]] },
  "Spire":    { c: "#0fb9b1", p: [[0,0,1,0],[0,0,1,0],[0,0,1,1],[0,1,0,1],[0,1,1,1],[1,1,1,1],[1,0,1,0],[0,0,0,0]] },
  "Helm":     { c: "#636e72", p: [[0,1,1,1],[1,1,1,1],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,0,1,0],[0,0,0,0],[0,0,0,0]] },
  "Torque":   { c: "#f9ca24", p: [[1,0,0,0],[1,1,1,0],[0,1,1,1],[0,1,0,1],[0,1,1,1],[1,1,1,0],[1,0,0,0],[0,0,0,0]] },
  "Oxide":    { c: "#e67e22", p: [[0,0,0,0],[0,0,1,0],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,0],[0,1,1,0],[1,0,0,1]] },
  "Aegis":    { c: "#27ae60", p: [[0,0,1,0],[0,1,1,1],[1,1,1,1],[1,1,0,1],[1,1,1,1],[0,1,1,1],[0,0,1,0],[0,0,1,0]] },
  "Flux":     { c: "#9b59b6", p: [[1,0,0,1],[0,1,1,1],[0,1,1,1],[1,1,0,1],[0,1,1,0],[0,1,1,1],[1,0,0,1],[0,0,0,0]] },
  "Pylon":    { c: "#1dd1a1", p: [[0,0,1,0],[0,0,1,1],[0,1,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,1],[1,1,1,1],[0,0,0,0]] },
  "Monolith": { c: "#576574", p: [[0,0,1,1],[0,1,1,1],[0,1,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,1],[0,0,1,0],[0,0,0,0]] },
  "Volt":     { c: "#feca57", p: [[0,0,0,0],[1,1,0,1],[1,1,1,1],[0,1,0,1],[1,1,1,0],[1,1,1,1],[0,0,0,0],[0,0,0,0]] },
  "Nimbus":   { c: "#54a0ff", p: [[0,1,1,1],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,0,1,1],[0,0,0,0],[0,0,0,0],[0,0,0,0]] },
  "Rook":     { c: "#ee5253", p: [[1,0,1,0],[1,1,1,1],[0,1,1,1],[0,1,0,1],[0,1,1,1],[1,1,1,1],[0,1,0,1],[0,0,0,0]] },
  "Specter":  { c: "#c8d6e5", p: [[0,0,1,0],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,0],[0,1,0,1],[0,0,0,0],[0,0,0,0]] },
  "Obelisk":  { c: "#78e08f", p: [[0,0,1,0],[0,0,1,1],[0,1,0,1],[0,1,1,1],[0,1,1,1],[0,1,0,1],[0,0,1,0],[0,0,0,0]] },
  "Arc":      { c: "#e77f67", p: [[0,1,1,0],[1,0,0,0],[1,1,1,1],[1,1,0,1],[1,1,1,1],[1,0,0,0],[0,1,1,0],[0,0,0,0]] },
  "Beacon":   { c: "#3dc1d3", p: [[0,0,1,0],[0,0,1,1],[0,1,1,1],[1,1,0,1],[1,1,1,1],[1,1,1,1],[1,0,0,1],[0,0,0,0]] },
  "Comet":    { c: "#f8a5c2", p: [[0,0,0,1],[0,1,1,1],[0,1,1,1],[0,1,0,1],[1,1,1,1],[1,1,0,0],[0,1,0,0],[0,0,0,0]] },
  "Nexus":    { c: "#6a89cc", p: [[0,0,0,0],[0,1,1,0],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,0],[0,0,0,0],[0,0,0,0]] },
  "Cipher":   { c: "#38ada9", p: [[1,0,0,0],[0,1,0,0],[0,1,1,1],[1,1,0,1],[0,1,1,0],[0,1,0,0],[1,0,0,0],[0,0,0,0]] },
  "Strider":  { c: "#fa983a", p: [[0,0,1,0],[0,1,1,1],[1,1,1,1],[0,1,0,1],[0,1,1,0],[0,1,0,1],[1,0,0,1],[0,0,0,0]] },
  "Glyph":    { c: "#b71540", p: [[0,1,0,1],[0,1,1,1],[1,1,1,1],[1,1,0,1],[0,1,1,1],[0,1,1,0],[0,1,0,1],[0,0,0,0]] },
  "Vertex":   { c: "#0abde3", p: [[0,0,1,0],[0,1,1,0],[1,1,1,1],[0,1,0,1],[1,1,1,1],[0,1,1,0],[0,0,1,0],[0,0,0,0]] },
};

// Auto-assign colors to agents that don't have one
const PALETTE = [
  '#58abf5', '#f5a623', '#b47aff', '#50e3c2', '#ff6b6b', '#ffd60a',
  '#30d158', '#ff2d55', '#5ac8fa', '#af52de', '#ff9500', '#00c7be',
];

// --- Filesystem helpers ---
function isDir(p) {
  try { return fs.statSync(p).isDirectory(); } catch { return false; }
}

function fileExists(p) {
  try { return fs.statSync(p).isFile(); } catch { return false; }
}

function safePath(base, requested) {
  const resolved = path.resolve(base, requested);
  if (!resolved.startsWith(path.resolve(base))) return null;
  return resolved;
}

// --- Skill scanning ---
function scanSkillDir(skillsDir) {
  const skills = [];
  if (!isDir(skillsDir)) return skills;
  for (const entry of fs.readdirSync(skillsDir)) {
    if (entry.startsWith('.')) continue;
    const entryPath = path.join(skillsDir, entry);
    if (!isDir(entryPath)) continue;
    const skillFile = path.join(entryPath, 'SKILL.md');
    if (!fileExists(skillFile)) continue;
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

// --- Platform detection ---
function detectSkillDirs(workspace) {
  const dirs = [];
  // Claude Code: .claude/skills/
  const cc = path.join(workspace, '.claude', 'skills');
  if (isDir(cc)) dirs.push({ path: cc, platform: 'claude-code' });
  // OpenClaw: skills/
  const oc = path.join(workspace, 'skills');
  if (isDir(oc)) dirs.push({ path: oc, platform: 'openclaw' });
  // Antigravity: .agent/skills/
  const ag = path.join(workspace, '.agent', 'skills');
  if (isDir(ag)) dirs.push({ path: ag, platform: 'antigravity' });
  return dirs;
}

function detectAgentWorkspaces(root) {
  const workspaces = [];
  // Check root itself
  const rootDirs = detectSkillDirs(root);
  if (rootDirs.length > 0) {
    workspaces.push({ path: root, skillDirs: rootDirs, isRoot: true });
  }
  // Check agents/ subdirectory (Claude Code pattern)
  const agentsDir = path.join(root, 'agents');
  if (isDir(agentsDir)) {
    for (const entry of fs.readdirSync(agentsDir)) {
      const agentPath = path.join(agentsDir, entry);
      if (!isDir(agentPath)) continue;
      const dirs = detectSkillDirs(agentPath);
      if (dirs.length > 0) {
        workspaces.push({ path: agentPath, skillDirs: dirs, isRoot: false, dirName: entry });
      }
    }
  }
  // Check direct subdirectories (OpenClaw multi-agent pattern)
  for (const entry of fs.readdirSync(root)) {
    if (entry === 'agents' || entry === 'node_modules' || entry.startsWith('.')) continue;
    const subPath = path.join(root, entry);
    if (!isDir(subPath)) continue;
    const dirs = detectSkillDirs(subPath);
    if (dirs.length > 0 && !workspaces.some(w => w.path === subPath)) {
      workspaces.push({ path: subPath, skillDirs: dirs, isRoot: false, dirName: entry });
    }
  }
  return workspaces;
}

// --- Build skill tree data ---
function buildSkillTree() {
  const config = loadConfig();
  const agents = [];
  const skillMap = {};
  let colorIdx = 0;

  function nextColor() {
    return PALETTE[colorIdx++ % PALETTE.length];
  }

  // If config has agents defined, use those as the base
  const configAgents = config?.agents || [];
  const configSkillDirs = config?.skillDirs || [];

  // Auto-detect workspaces
  const workspaces = detectAgentWorkspaces(SKILL_TREE_ROOT);
  console.log(`  Scanned ${SKILL_TREE_ROOT}`);
  console.log(`  Found ${workspaces.length} workspace(s)`);

  // Build agent list from workspaces
  for (const ws of workspaces) {
    if (ws.isRoot) continue; // Root skills are shared, handled below
    const dirName = ws.dirName || path.basename(ws.path);
    const agentId = dirName.toLowerCase();

    // Check if config has overrides for this agent
    const cfgAgent = configAgents.find(a => a.id === agentId || a.id === dirName);

    // Try to read agent name from CLAUDE.md, IDENTITY.md, or config
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

    // Scan skills for this agent
    const agentSkillIds = [];
    for (const sd of ws.skillDirs) {
      const skills = scanSkillDir(sd.path);
      for (const s of skills) {
        agentSkillIds.push(s.id);
        if (!skillMap[s.id]) {
          skillMap[s.id] = { ...s, agents: [] };
        }
        if (!skillMap[s.id].agents.includes(agentId)) {
          skillMap[s.id].agents.push(agentId);
        }
      }
    }

    agents.push({
      id: agentId,
      name: displayName,
      color,
      icon,
      role,
      workspace: ws.path,
      skills: agentSkillIds,
      customPixels: cfgAgent?.pixels || null,
    });
  }

  // Handle root/shared skills — link to all agents
  const rootWs = workspaces.find(w => w.isRoot);
  if (rootWs) {
    const allAgentIds = agents.map(a => a.id);
    for (const sd of rootWs.skillDirs) {
      const skills = scanSkillDir(sd.path);
      for (const s of skills) {
        if (!skillMap[s.id]) {
          skillMap[s.id] = { ...s, agents: [...allAgentIds], shared: true };
        } else {
          for (const aid of allAgentIds) {
            if (!skillMap[s.id].agents.includes(aid)) skillMap[s.id].agents.push(aid);
          }
          skillMap[s.id].shared = true;
        }
        for (const agent of agents) {
          if (!agent.skills.includes(s.id)) agent.skills.push(s.id);
        }
      }
    }
  }

  // Handle extra skillDirs from config
  for (const dir of configSkillDirs) {
    const resolved = path.resolve(SKILL_TREE_ROOT, dir);
    if (!isDir(resolved)) continue;
    const skills = scanSkillDir(resolved);
    const allAgentIds = agents.map(a => a.id);
    for (const s of skills) {
      if (!skillMap[s.id]) {
        skillMap[s.id] = { ...s, agents: [...allAgentIds], shared: true };
      }
    }
  }

  // If no agents found, create a single "workspace" agent from root
  if (agents.length === 0 && Object.keys(skillMap).length > 0) {
    agents.push({
      id: 'workspace',
      name: 'Workspace',
      color: PALETTE[0],
      icon: 'Robo',
      role: '',
      workspace: SKILL_TREE_ROOT,
      skills: Object.keys(skillMap),
      customPixels: null,
    });
    for (const s of Object.values(skillMap)) {
      if (s.agents.length === 0) s.agents.push('workspace');
    }
  }

  console.log(`  ${agents.length} agent(s), ${Object.keys(skillMap).length} skill(s)`);

  return { agents, skills: Object.values(skillMap) };
}

// --- Collect all skill directories for content serving ---
function getAllSkillDirs() {
  const dirs = new Set();
  const config = loadConfig();
  const workspaces = detectAgentWorkspaces(SKILL_TREE_ROOT);
  for (const ws of workspaces) {
    for (const sd of ws.skillDirs) dirs.add(sd.path);
  }
  for (const dir of (config?.skillDirs || [])) {
    const resolved = path.resolve(SKILL_TREE_ROOT, dir);
    if (isDir(resolved)) dirs.add(resolved);
  }
  return [...dirs];
}

// --- MIME ---
const MIME = {
  '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
  '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
  '.woff2': 'font/woff2',
};

function sendJSON(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

// --- HTTP Server ---
const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const pathname = url.pathname;

  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  if (req.method === 'OPTIONS') { res.writeHead(204); res.end(); return; }

  // --- Static files ---
  if (pathname === '/' || pathname === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(fs.readFileSync(path.join(__dirname, 'index.html')));
    return;
  }
  if (pathname === '/icons' || pathname === '/icons.html') {
    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(fs.readFileSync(path.join(__dirname, 'icons.html')));
    return;
  }

  // --- API: Skill Tree ---
  if (pathname === '/api/skill-tree') {
    const data = buildSkillTree();
    // Include icon library so the frontend can resolve icons by name
    data.iconLibrary = ICON_LIBRARY;
    sendJSON(res, data);
    return;
  }

  // --- API: Skill content ---
  if (pathname.startsWith('/api/skills/') && pathname.endsWith('/content')) {
    const skillId = decodeURIComponent(pathname.replace('/api/skills/', '').replace('/content', ''));
    if (skillId.includes('..') || skillId.includes('/') || skillId.includes('\\')) {
      sendJSON(res, { error: 'Invalid skill ID' }, 400);
      return;
    }
    const dirs = getAllSkillDirs();
    for (const dir of dirs) {
      const skillFile = path.join(dir, skillId, 'SKILL.md');
      const resolved = path.resolve(skillFile);
      // Path traversal check
      if (!resolved.startsWith(path.resolve(dir))) continue;
      if (fileExists(resolved)) {
        const content = fs.readFileSync(resolved, 'utf8');
        sendJSON(res, { id: skillId, content });
        return;
      }
    }
    sendJSON(res, { error: 'Skill not found' }, 404);
    return;
  }

  // --- API: Agent doc ---
  if (pathname.startsWith('/api/agent-doc/')) {
    const parts = pathname.replace('/api/agent-doc/', '').split('/');
    const agentId = decodeURIComponent(parts[0]);
    const docType = parts[1] || 'claude';
    if (agentId.includes('..') || docType.includes('..')) {
      sendJSON(res, { error: 'Invalid path' }, 400);
      return;
    }

    const config = loadConfig();
    const docPaths = config?.docPaths || { claude: 'CLAUDE.md', soul: 'SOUL.md' };
    const fileName = docPaths[docType];
    if (!fileName) { sendJSON(res, { error: 'Unknown doc type' }, 404); return; }

    // Find the agent's workspace
    const workspaces = detectAgentWorkspaces(SKILL_TREE_ROOT);
    const configAgents = config?.agents || [];
    const cfgAgent = configAgents.find(a => a.id === agentId);
    let workspace = cfgAgent?.workspace ? path.resolve(SKILL_TREE_ROOT, cfgAgent.workspace) : null;

    if (!workspace) {
      const ws = workspaces.find(w => !w.isRoot && (w.dirName || path.basename(w.path)).toLowerCase() === agentId);
      if (ws) workspace = ws.path;
    }
    if (!workspace) { sendJSON(res, { error: 'Agent not found' }, 404); return; }

    const docPath = path.resolve(workspace, fileName);
    // Path traversal check
    if (!docPath.startsWith(path.resolve(workspace))) {
      sendJSON(res, { error: 'Invalid path' }, 400);
      return;
    }

    try {
      const content = fs.readFileSync(docPath, 'utf8');
      sendJSON(res, { content });
    } catch {
      sendJSON(res, { error: `${fileName} not found` }, 404);
    }
    return;
  }

  // --- API: Icon library ---
  if (pathname === '/api/icons') {
    sendJSON(res, ICON_LIBRARY);
    return;
  }

  // --- 404 ---
  res.writeHead(404);
  res.end('Not found');
});

server.on('error', (e) => {
  if (e.code === 'EADDRINUSE') {
    console.error(`\n  Port ${PORT} is already in use.\n  Set a different port: PORT=5051 node server.js\n  Or set PORT in .env\n`);
    process.exit(1);
  }
  throw e;
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`\n  Skill Tree`);
  console.log(`  http://localhost:${PORT}`);
  console.log(`  Icon Gallery: http://localhost:${PORT}/icons`);
  console.log(`  Scanning: ${SKILL_TREE_ROOT}`);
  console.log(`  Platform: ${PLATFORM}\n`);
  // Trigger initial scan to log results
  buildSkillTree();
  console.log('');
});
