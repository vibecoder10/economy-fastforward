import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { exec, execSync, spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '5050', 10);
const DATA_DIR = path.join(__dirname, 'data');
const PRD_QUEUE_FILE = path.join(DATA_DIR, 'prd-queue.json');

// ─── PRD Queue System ─────────────────────────────────────────────────────
// Stores multiple PRDs. When current PRD completes, next one auto-deploys.
function readPrdQueue() {
  try { return JSON.parse(fs.readFileSync(PRD_QUEUE_FILE, 'utf8')); }
  catch { return { queue: [], deployed: [], current_index: -1 }; }
}
function writePrdQueue(q) { fs.writeFileSync(PRD_QUEUE_FILE, JSON.stringify(q, null, 2)); }

function deployNextPrd(server_url) {
  const q = readPrdQueue();
  const nextIndex = q.current_index + 1;
  if (nextIndex >= q.queue.length) {
    console.log('PRD Queue: all PRDs completed');
    q.current_index = q.queue.length; // mark exhausted
    writePrdQueue(q);
    return false;
  }
  const nextPrd = q.queue[nextIndex];
  q.current_index = nextIndex;
  q.queue[nextIndex].started_at = new Date().toISOString();
  writePrdQueue(q);
  console.log(`PRD Queue: auto-deploying PRD ${nextIndex + 1}/${q.queue.length} — "${nextPrd.title}"`);
  // Trigger deploy via internal HTTP call (reuses existing deploy-prd logic)
  const postData = JSON.stringify({ content: nextPrd.content });
  const req = http.request({ hostname: 'localhost', port: PORT, path: '/api/deploy-prd', method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(postData) }
  }, (res) => {
    let body = '';
    res.on('data', d => body += d);
    res.on('end', () => console.log(`PRD Queue: deploy response — ${body}`));
  });
  req.on('error', e => console.error(`PRD Queue: deploy failed — ${e.message}`));
  req.write(postData);
  req.end();
  return true;
}

// Auto-cadence: boost to 'max' on PRD deploy, restore when PRD completes
const PRD_BOOST_CADENCE = 'max';

const CADENCE_SCHEDULES = {
  light:  { backend: '0 0,4,8,12,16,20 * * *', frontend: '2 0,4,8,12,16,20 * * *', qa: '4 0,4,8,12,16,20 * * *', security: '20 0,8,16 * * *', tester: '30 0,4,8,12,16,20 * * *', micro: '35 0,4,8,12,16,20 * * *', label: '6x/day (every 4h)' },
  normal: { backend: '0 */2 * * *',             frontend: '2 */2 * * *',             qa: '4 */2 * * *',             security: '20 */4 * * *',      tester: '25 */2 * * *',             micro: '30 */2 * * *',             label: '12x/day (every 2h)' },
  fast:   { backend: '0 * * * *',               frontend: '2 * * * *',               qa: '4 * * * *',               security: '20 */4 * * *',      tester: '35 * * * *',               micro: '45 * * * *',               label: '24x/day (every 1h)' },
  max:    { backend: '0,30 * * * *',             frontend: '2,32 * * * *',            qa: '4,34 * * * *',            security: '20 */2 * * *',      tester: '18,48 * * * *',            micro: '24,54 * * * *',            label: '48x/day (every 30m)' },
  turbo:  { backend: '0,15,30,45 * * * *',       frontend: '2,17,32,47 * * * *',      qa: '4,19,34,49 * * * *',      security: '20 * * * *',        tester: '10,25,40,55 * * * *',      micro: '12,27,42,57 * * * *',      label: '96x/day (every 15m)' },
  ultra:  { backend: '*/8 * * * *',              frontend: '1-59/8 * * * *',           qa: '2-59/8 * * * *',           security: '3-59/8 * * * *',   tester: '4-59/8 * * * *',           micro: '6-59/8 * * * *',           label: '180x/day (every 8m)' },
};

function syncCronsJson(sched) {
  // Keep the Crons dashboard in sync with the actual crontab
  const cronsFile = path.join(__dirname, '../crons/data/crons.json');
  try {
    const cronsData = {
      description: 'StoryEngine Agent Schedule — Build → QA → Tester finds bugs → Orchestrator plans fixes',
      crons: [
        { id: 'orchestrator-grand', name: 'Orchestrator — Grand Audit (daily)', cron: '0 5 * * *', enabled: true },
        { id: 'planning-session', name: 'Planning Session (daily)', cron: '0 6 * * *', enabled: true },
        { id: 'morning-briefing', name: 'Morning Briefing (daily)', cron: '0 7 * * *', enabled: true },
        { id: 'backend-dev', name: 'Backend Dev — Build', cron: sched.backend, enabled: true },
        { id: 'frontend-dev', name: 'Frontend Dev — Wire', cron: sched.frontend, enabled: true },
        { id: 'qa-engineer', name: 'QA Engineer — Verify', cron: sched.qa, enabled: true },
        { id: 'security-auditor', name: 'Security Auditor — Scan', cron: sched.security, enabled: true },
        { id: 'pipeline-tester', name: 'Pipeline Tester — Click Through App', cron: sched.tester, enabled: true },
        { id: 'orchestrator-micro', name: 'Orchestrator — Micro Review', cron: sched.micro, enabled: true },
        { id: 'daily-report', name: 'Daily Report + PR', cron: '0 23 * * *', enabled: true },
        { id: 'calculate-skills', name: 'Calculate Agent Skills', cron: '5 23 * * *', enabled: true },
        { id: 'retro', name: 'Daily Retrospective', cron: '10 23 * * *', enabled: true },
        { id: 'rubric-healthcheck', name: 'RUBRIC Server Healthcheck', cron: '*/5 * * * *', enabled: true },
      ],
    };
    fs.writeFileSync(cronsFile, JSON.stringify(cronsData, null, 2) + '\n');
  } catch (e) {
    console.error('syncCronsJson failed:', e.message);
  }
}

function setCadence(cadence) {
  const controlsFile = path.join(DATA_DIR, 'controls.json');
  let controls = {};
  try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
  controls.cadence = cadence;
  fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));

  const agentsDir = path.join(__dirname, '../../storyengine/agents');
  const logDir = '/tmp/storyengine-agents';
  const sched = CADENCE_SCHEDULES[cadence] || CADENCE_SCHEDULES.fast;
  try {
    const cronLines = [
      `0 5 * * * cd ${agentsDir} && ORCHESTRATOR_MODE=grand bash run-agent.sh orchestrator >> ${logDir}/orchestrator.log 2>&1 # storyengine-agents`,
      `${sched.backend} cd ${agentsDir} && bash run-agent.sh backend-dev >> ${logDir}/backend-dev.log 2>&1 # storyengine-agents`,
      `${sched.frontend} cd ${agentsDir} && bash run-agent.sh frontend-dev >> ${logDir}/frontend-dev.log 2>&1 # storyengine-agents`,
      `${sched.qa} cd ${agentsDir} && bash run-agent.sh qa-engineer >> ${logDir}/qa-engineer.log 2>&1 # storyengine-agents`,
      `${sched.security} cd ${agentsDir} && bash run-agent.sh security-auditor >> ${logDir}/security-auditor.log 2>&1 # storyengine-agents`,
      `${sched.micro} cd ${agentsDir} && ORCHESTRATOR_MODE=micro bash run-agent.sh orchestrator >> ${logDir}/orchestrator-micro.log 2>&1 # storyengine-agents`,
      `${sched.tester} cd ${agentsDir} && bash run-agent.sh pipeline-tester >> ${logDir}/pipeline-tester.log 2>&1 # storyengine-agents`,
      `0 6 * * * cd ${agentsDir} && bash planning-session.sh >> ${logDir}/planning-session.log 2>&1 # storyengine-agents`,
      `0 7 * * * cd ${agentsDir} && bash morning-briefing.sh >> ${logDir}/morning-briefing.log 2>&1 # storyengine-agents`,
      `0 23 * * * cd ${agentsDir} && bash daily-report.sh >> ${logDir}/daily-report.log 2>&1 # storyengine-agents`,
      `5 23 * * * cd ${agentsDir} && bash calculate-skills.sh >> ${logDir}/calculate-skills.log 2>&1 # storyengine-agents`,
      `10 23 * * * cd ${agentsDir} && bash retro.sh >> ${logDir}/retro.log 2>&1 # storyengine-agents`,
      `*/5 * * * * pgrep -f 'rubric.*server' > /dev/null || (cd ${path.join(__dirname)} && nohup node server.js > ${logDir}/rubric.log 2>&1 &) # storyengine-agents`,
    ];
    const existing = execSync('crontab -l 2>/dev/null || echo ""', { encoding: 'utf8' });
    const nonAgent = existing.split('\n').filter(l => !l.includes('storyengine-agents')).join('\n');
    const newCrontab = nonAgent.trim() + '\n\n# === StoryEngine Agents ===\n' + cronLines.join('\n') + '\n';
    const tmpFile = '/tmp/cron-cadence.txt';
    fs.writeFileSync(tmpFile, newCrontab);
    execSync(`crontab ${tmpFile}`);
    fs.unlinkSync(tmpFile);
    // Sync the Crons dashboard data file with the actual schedule
    syncCronsJson(sched);
    console.log(`Cadence set to ${cadence} (${sched.label})`);
    return { success: true, cadence, label: sched.label };
  } catch (e) {
    console.error('setCadence failed:', e.message);
    return { success: false, error: String(e) };
  }
}

// --- Node version check ---
const [major] = process.versions.node.split('.').map(Number);
if (major < 18) {
  console.error(`\n  Rubric Console requires Node.js 18+. You are running ${process.version}.\n`);
  process.exit(1);
}

// Ensure data dir exists
if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });

// Resolve Claude CLI path (npm global bin may not be in non-interactive PATH)
const CLAUDE_BIN = process.env.CLAUDE_BIN || (() => {
  const candidates = [
    path.join(process.env.HOME || require('os').homedir(), '.npm-global/bin/claude'),
    '/usr/local/bin/claude',
    'claude'
  ];
  for (const c of candidates) { try { if (fs.existsSync(c)) return c; } catch {} }
  return 'claude';
})();

console.log('CLAUDE_BIN resolved to:', CLAUDE_BIN);

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
const TAB_ORDER = ['welcome', 'activity', 'agents', 'flows', 'skill-trees', 'crons', 'team', 'icons'];
const INSTALLED_TABS = ['welcome', 'activity', ...INSTALLED, 'icons']
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
  : path.resolve(__dirname, '../../');

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

  // Add config-defined agents that weren't found by workspace scanning
  for (const cfgAgent of cfgAgents) {
    if (!agents.find(a => a.id === cfgAgent.id)) {
      agents.push({
        id: cfgAgent.id,
        name: cfgAgent.name || cfgAgent.id,
        color: cfgAgent.color || nextColor(),
        icon: cfgAgent.icon || 'Robo',
        role: cfgAgent.role || '',
        workspace: cfgAgent.workspace ? path.resolve(SKILL_TREE_ROOT, cfgAgent.workspace) : null,
        skills: [],
        customPixels: cfgAgent.pixels || null,
      });
    }
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

  // POST /api/activity-log — append a run entry
  if (pathname === '/api/activity-log' && req.method === 'POST') {
    let body;
    try { body = JSON.parse(await readBody(req)); } catch (e) { sendJSON(res, { error: 'Invalid JSON: ' + e.message }, 400); return; }
    const logFile = path.join(DATA_DIR, 'activity-log.json');
    let log = [];
    try { log = JSON.parse(fs.readFileSync(logFile, 'utf8')); } catch {}
    const entry = {
      agent: body.agent || 'unknown',
      task: body.task || '',
      summary: body.summary || '',
      status: body.status || 'completed',
      timestamp: Date.now(),
    };
    if (body.duration_seconds != null) entry.duration_seconds = Number(body.duration_seconds);
    if (body.estimated_cost != null) entry.estimated_cost = Number(body.estimated_cost);
    if (body.model) entry.model = body.model;
    if (body.detail) entry.detail = body.detail;
    if (body.detail_file) entry.detail_file = body.detail_file;
    log.unshift(entry);
    // Keep last 200 entries
    if (log.length > 200) log = log.slice(0, 200);
    fs.writeFileSync(logFile, JSON.stringify(log, null, 2));
    sendJSON(res, { success: true });
    return;
  }

  // GET /api/activity-log — read the activity feed
  if (pathname === '/api/activity-log' && req.method === 'GET') {
    const logFile = path.join(DATA_DIR, 'activity-log.json');
    let log = [];
    try { log = JSON.parse(fs.readFileSync(logFile, 'utf8')); } catch {}
    const limit = parseInt(url.searchParams?.get('limit') || new URL('http://x' + pathname + '?' + (req.url.split('?')[1] || '')).searchParams.get('limit')) || 50;
    sendJSON(res, log.slice(0, limit));
    return;
  }

  // DELETE /api/activity-log — clear the activity feed
  if (pathname === '/api/activity-log' && req.method === 'DELETE') {
    const logFile = path.join(DATA_DIR, 'activity-log.json');
    fs.writeFileSync(logFile, '[]');
    sendJSON(res, { success: true, message: 'Activity log cleared' });
    return;
  }

  // POST /api/controls/cadence — update agent cron frequency
  if (pathname === '/api/controls/cadence' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const result = setCadence(body.cadence);
    sendJSON(res, result, result.success ? 200 : 500);
    return;
  }

  // GET /api/screenshots/:filename — serve QA screenshots
  if (pathname.startsWith('/api/screenshots/') && req.method === 'GET') {
    const filename = pathname.replace('/api/screenshots/', '');
    if (filename.includes('..') || !filename.match(/\.(png|jpg|jpeg|gif|webp)$/i)) {
      sendJSON(res, { error: 'Invalid file' }, 400);
      return;
    }
    const screenshotDir = path.join(__dirname, '../../storyengine/agents/screenshots');
    const filePath = path.join(screenshotDir, filename);
    try {
      const data = fs.readFileSync(filePath);
      const ext = filename.split('.').pop().toLowerCase();
      const mime = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif', webp: 'image/webp' }[ext] || 'image/png';
      res.writeHead(200, { 'Content-Type': mime, 'Cache-Control': 'public, max-age=3600' });
      res.end(data);
    } catch { res.writeHead(404); res.end('Not found'); }
    return;
  }

  // GET /api/screenshots — list all screenshots
  if (pathname === '/api/screenshots' && req.method === 'GET') {
    const screenshotDir = path.join(__dirname, '../../storyengine/agents/screenshots');
    try {
      const files = fs.readdirSync(screenshotDir)
        .filter(f => f.match(/\.(png|jpg|jpeg|gif|webp)$/i))
        .map(f => ({ name: f, url: '/api/screenshots/' + f, modified: fs.statSync(path.join(screenshotDir, f)).mtimeMs }))
        .sort((a, b) => b.modified - a.modified);
      sendJSON(res, files);
    } catch { sendJSON(res, []); }
    return;
  }

  // GET /api/pull-requests — fetch open PRs from GitHub
  if (pathname === '/api/pull-requests' && req.method === 'GET') {
    try {
      const agentDir = path.join(__dirname, '../../storyengine/agents');
      const out = execSync('gh pr list --state open --json number,title,url,additions,deletions,changedFiles,createdAt,headRefName --limit 5 2>/dev/null || echo "[]"', {
        cwd: agentDir, timeout: 10000, encoding: 'utf8'
      });
      sendJSON(res, JSON.parse(out.trim() || '[]'));
    } catch { sendJSON(res, []); }
    return;
  }

  // GET /api/activity-log/detail — read a full agent report file
  if (pathname === '/api/activity-log/detail' && req.method === 'GET') {
    const params = new URL('http://x' + req.url).searchParams;
    const file = params.get('file');
    if (!file || file.includes('..') || !file.endsWith('.md')) {
      sendJSON(res, { error: 'Invalid file' }, 400);
      return;
    }
    const reportsDir = path.join(__dirname, '../../storyengine/agents/reports');
    const filePath = path.join(reportsDir, file);
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      sendJSON(res, { file, content });
    } catch {
      sendJSON(res, { error: 'Report not found' }, 404);
    }
    return;
  }

  // POST /api/controls/focus — set a high-level directive for all agents
  if (pathname === '/api/controls/focus' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    controls.focus = body.focus || '';
    fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    sendJSON(res, { success: true, focus: controls.focus });
    return;
  }

  // ===== HANDOFF ROUTES =====

  // POST /api/handoffs — create a handoff note
  if (pathname === '/api/handoffs' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const handoffsFile = path.join(DATA_DIR, 'handoffs.json');
    let handoffs = [];
    try { handoffs = JSON.parse(fs.readFileSync(handoffsFile, 'utf8')); } catch {}
    handoffs.unshift({
      id: 'h-' + Date.now(),
      from: body.from,
      to: body.to,
      task_id: body.task_id || '',
      message: body.message || '',
      files_changed: body.files_changed || [],
      endpoint_details: body.endpoint_details || null,
      read: false,
      timestamp: Date.now(),
    });
    if (handoffs.length > 100) handoffs = handoffs.slice(0, 100);
    fs.writeFileSync(handoffsFile, JSON.stringify(handoffs, null, 2));
    sendJSON(res, { success: true });
    return;
  }

  // POST /api/handoffs/:id/read — mark handoff as read
  if (pathname.startsWith('/api/handoffs/') && pathname.endsWith('/read') && req.method === 'POST') {
    const id = pathname.replace('/api/handoffs/', '').replace('/read', '');
    const handoffsFile = path.join(DATA_DIR, 'handoffs.json');
    let handoffs = [];
    try { handoffs = JSON.parse(fs.readFileSync(handoffsFile, 'utf8')); } catch {}
    const entry = handoffs.find(h => h.id === id);
    if (!entry) { sendJSON(res, { error: 'Not found' }, 404); return; }
    entry.read = true;
    fs.writeFileSync(handoffsFile, JSON.stringify(handoffs, null, 2));
    sendJSON(res, { success: true });
    return;
  }

  // GET /api/handoffs — list handoffs with optional filters
  if (pathname === '/api/handoffs' && req.method === 'GET') {
    const handoffsFile = path.join(DATA_DIR, 'handoffs.json');
    let handoffs = [];
    try { handoffs = JSON.parse(fs.readFileSync(handoffsFile, 'utf8')); } catch {}
    const toFilter = url.searchParams.get('to');
    const unreadOnly = url.searchParams.get('unread') === 'true';
    if (toFilter) handoffs = handoffs.filter(h => h.to === toFilter);
    if (unreadOnly) handoffs = handoffs.filter(h => !h.read);
    sendJSON(res, handoffs);
    return;
  }

  // ===== LOG VIEWING (Feature 4) =====

  // GET /api/logs — list available agent log files
  if (pathname === '/api/logs' && req.method === 'GET') {
    const logDir = '/tmp/storyengine-agents';
    try {
      const files = fs.readdirSync(logDir).filter(f => f.endsWith('.log'));
      const logs = files.map(f => {
        const stat = fs.statSync(path.join(logDir, f));
        return { name: f, agent: f.replace('.log', ''), size: stat.size, modified: stat.mtimeMs };
      }).sort((a, b) => b.modified - a.modified);
      sendJSON(res, logs);
    } catch { sendJSON(res, []); }
    return;
  }

  // GET /api/logs/:agent — tail last N lines of an agent's log
  if (pathname.startsWith('/api/logs/') && req.method === 'GET') {
    const agentId = pathname.split('/api/logs/')[1];
    if (!/^[a-z0-9-]+$/.test(agentId)) { sendJSON(res, { error: 'Invalid agent ID' }, 400); return; }
    const logDir = '/tmp/storyengine-agents';
    const logFile = path.join(logDir, agentId + '.log');
    if (!fs.existsSync(logFile)) { sendJSON(res, { error: 'Log not found' }, 404); return; }
    try {
      const lines = parseInt(url.searchParams.get('lines') || '200', 10);
      const content = execSync(`tail -n ${Math.min(lines, 1000)} "${logFile}"`, { encoding: 'utf8', maxBuffer: 1024 * 1024 });
      const stat = fs.statSync(logFile);
      sendJSON(res, { agent: agentId, content, size: stat.size, modified: stat.mtimeMs });
    } catch (e) { sendJSON(res, { error: e.message }, 500); }
    return;
  }

  // ===== COST SUMMARY (Feature 3) =====

  // GET /api/cost-summary — aggregate costs from activity log
  if (pathname === '/api/cost-summary' && req.method === 'GET') {
    const logFile = path.join(DATA_DIR, 'activity-log.json');
    let log = [];
    try { log = JSON.parse(fs.readFileSync(logFile, 'utf8')); } catch {}
    const now = Date.now();
    const DAY = 86400000;
    const periods = { '24h': now - DAY, '7d': now - 7 * DAY, '30d': now - 30 * DAY };
    const summary = {};
    for (const [period, since] of Object.entries(periods)) {
      const entries = log.filter(e => e.timestamp >= since && e.estimated_cost != null);
      const byAgent = {};
      let totalCost = 0, totalDuration = 0, totalRuns = 0;
      for (const e of entries) {
        const a = e.agent || 'unknown';
        if (!byAgent[a]) byAgent[a] = { cost: 0, duration: 0, runs: 0, errors: 0 };
        byAgent[a].cost += e.estimated_cost || 0;
        byAgent[a].duration += e.duration_seconds || 0;
        byAgent[a].runs++;
        if (e.status === 'error' || e.status === 'timeout') byAgent[a].errors++;
        totalCost += e.estimated_cost || 0;
        totalDuration += e.duration_seconds || 0;
        totalRuns++;
      }
      summary[period] = { totalCost: Math.round(totalCost * 100) / 100, totalDuration, totalRuns, byAgent };
    }
    sendJSON(res, summary);
    return;
  }

  // ===== RUN HISTORY (Feature 6) =====

  // GET /api/run-history — extract actual run windows from activity log
  if (pathname === '/api/run-history' && req.method === 'GET') {
    const logFile = path.join(DATA_DIR, 'activity-log.json');
    let log = [];
    try { log = JSON.parse(fs.readFileSync(logFile, 'utf8')); } catch {}
    const DAY = 86400000;
    const since = Date.now() - 7 * DAY;
    const runs = log
      .filter(e => e.timestamp >= since && (e.status === 'completed' || e.status === 'error' || e.status === 'timeout'))
      .map(e => ({
        agent: e.agent,
        end_time: e.timestamp,
        start_time: e.duration_seconds ? e.timestamp - (e.duration_seconds * 1000) : e.timestamp,
        duration_seconds: e.duration_seconds || null,
        status: e.status,
        summary: e.summary,
        estimated_cost: e.estimated_cost || null,
      }));
    sendJSON(res, runs);
    return;
  }

  // ===== CONTROLS ROUTES =====

  // GET /api/controls — read controls
  if (pathname === '/api/controls' && req.method === 'GET') {
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    sendJSON(res, controls);
    return;
  }

  // POST /api/controls/team-toggle — master ON/OFF for entire team
  if (pathname === '/api/controls/team-toggle' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { team_enabled: true, paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    controls.team_enabled = body.enabled !== undefined ? !!body.enabled : !controls.team_enabled;
    fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    
    // Explicitly add or remove crontab entries based on team state to prevent phantom crons
    if (controls.team_enabled) {
      setCadence(controls.cadence || 'fast');
      console.log('Team toggled ON: Restored background crontab schedules.');
    } else {
      try {
        const existing = execSync('crontab -l 2>/dev/null || echo ""', { encoding: 'utf8' });
        const nonAgent = existing.split('\n').filter(l => !l.includes('storyengine-agents')).join('\n');
        const tmpFile = '/tmp/cron-clean.txt';
        fs.writeFileSync(tmpFile, nonAgent.trim() + '\n');
        execSync(`crontab ${tmpFile}`);
        fs.unlinkSync(tmpFile);
        console.log('Team toggled OFF: Removed all background agent crontabs.');
      } catch (e) {
        console.error('Failed to clear crontab on team toggle OFF:', e);
      }
    }
    
    sendJSON(res, { success: true, team_enabled: controls.team_enabled });
    return;
  }

  // GET /api/team-mode — computed team mode (OFF, Ad-hoc, PRD, Background)
  if (pathname === '/api/team-mode' && req.method === 'GET') {
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { team_enabled: true };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    if (controls.team_enabled === false) {
      sendJSON(res, { mode: 'off', label: 'OFF', description: 'All agents stopped' });
      return;
    }
    // Check PRD
    const prdPath = path.join(__dirname, '../../agents/prd.json');
    let hasPRD = false;
    try { hasPRD = fs.existsSync(prdPath) && JSON.parse(fs.readFileSync(prdPath, 'utf8')).tasks?.length > 0; } catch {}
    if (hasPRD) {
      sendJSON(res, { mode: 'prd', label: 'PRD Mode', description: 'Executing PRD tasks' });
      return;
    }
    // Check task queue
    const queueFile = path.join(__dirname, '../../storyengine/agents/task-queue.json');
    let pendingTasks = 0;
    try {
      const q = JSON.parse(fs.readFileSync(queueFile, 'utf8'));
      pendingTasks = (q.tabs || []).flatMap(t => t.tasks || []).filter(t => t.status !== 'done' && t.status !== 'blocked').length;
    } catch {}
    if (pendingTasks > 0) {
      sendJSON(res, { mode: 'background', label: 'Background', description: pendingTasks + ' tasks in queue' });
      return;
    }
    sendJSON(res, { mode: 'adhoc', label: 'Ad-hoc', description: 'Responding to messages & errors' });
    return;
  }

  // POST /api/controls/pause — toggle agent pause
  if (pathname === '/api/controls/pause' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    if (!controls.paused_agents) controls.paused_agents = [];
    const idx = controls.paused_agents.indexOf(body.agent);
    if (idx >= 0) controls.paused_agents.splice(idx, 1);
    else controls.paused_agents.push(body.agent);
    fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    sendJSON(res, { success: true, paused_agents: controls.paused_agents });
    return;
  }

  // POST /api/controls/skip — skip a task
  if (pathname === '/api/controls/skip' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    if (!controls.skipped_tasks) controls.skipped_tasks = [];
    if (!controls.skipped_tasks.includes(body.task_id)) controls.skipped_tasks.push(body.task_id);
    fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    sendJSON(res, { success: true, skipped_tasks: controls.skipped_tasks });
    return;
  }

  // POST /api/controls/prioritize — set priority override
  if (pathname === '/api/controls/prioritize' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    if (!controls.priority_overrides) controls.priority_overrides = {};
    if (body.priority == null) delete controls.priority_overrides[body.task_id];
    else controls.priority_overrides[body.task_id] = body.priority;
    fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    sendJSON(res, { success: true, priority_overrides: controls.priority_overrides });
    return;
  }

  // ===== FEEDBACK ROUTES =====

  // POST /api/feedback — add operator feedback for all agents
  if (pathname === '/api/feedback' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    if (!controls.feedback) controls.feedback = [];
    controls.feedback.unshift({
      id: 'fb-' + Date.now(),
      message: body.message || '',
      timestamp: Date.now(),
      read_by: [],
    });
    if (controls.feedback.length > 50) controls.feedback = controls.feedback.slice(0, 50);
    fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    sendJSON(res, { success: true, id: controls.feedback[0].id });
    return;
  }

  // GET /api/feedback — list all feedback
  if (pathname === '/api/feedback' && req.method === 'GET') {
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = {};
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    sendJSON(res, controls.feedback || []);
    return;
  }

  // POST /api/feedback/:id/dismiss — remove feedback
  if (pathname.startsWith('/api/feedback/') && pathname.endsWith('/dismiss') && req.method === 'POST') {
    const id = pathname.replace('/api/feedback/', '').replace('/dismiss', '');
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    if (controls.feedback) {
      controls.feedback = controls.feedback.filter(fb => fb.id !== id);
      fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    }
    sendJSON(res, { success: true });
    return;
  }

  // POST /api/feedback/:id/read — mark feedback as read by an agent
  if (pathname.startsWith('/api/feedback/') && pathname.endsWith('/read') && req.method === 'POST') {
    const id = pathname.replace('/api/feedback/', '').replace('/read', '');
    const body = JSON.parse(await readBody(req));
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    let controls = { paused_agents: [], skipped_tasks: [], priority_overrides: {} };
    try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
    const entry = (controls.feedback || []).find(fb => fb.id === id);
    if (entry && body.agent && !entry.read_by.includes(body.agent)) {
      entry.read_by.push(body.agent);
      fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    }
    sendJSON(res, { success: true });
    return;
  }

  // ===== TASK QUEUE ROUTE =====

  // GET /api/task-queue — expose task queue (read-only)
  if (pathname === '/api/task-queue' && req.method === 'GET') {
    const queueFile = path.join(__dirname, '../../storyengine/agents/task-queue.json');
    let queue = [];
    try { queue = JSON.parse(fs.readFileSync(queueFile, 'utf8')); } catch {}
    sendJSON(res, queue);
    return;
  }

  // DELETE /api/task-queue — clear all tasks
  if (pathname === '/api/task-queue' && req.method === 'DELETE') {
    const queueFile = path.join(__dirname, '../../storyengine/agents/task-queue.json');
    const emptyQueue = { version: 2, current_tab: 0, last_updated: new Date().toISOString().slice(0, 10), last_updated_by: 'operator', tabs: [] };
    fs.writeFileSync(queueFile, JSON.stringify(emptyQueue, null, 2));
    sendJSON(res, { success: true });
    return;
  }

  // POST /api/task-queue/dismiss — dismiss a single task (mark as done)
  if (pathname === '/api/task-queue/dismiss' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const queueFile = path.join(__dirname, '../../storyengine/agents/task-queue.json');
    try {
      const queue = JSON.parse(fs.readFileSync(queueFile, 'utf8'));
      const tab = queue.tabs?.[body.tab_index];
      if (tab?.tasks?.[body.task_index]) {
        tab.tasks[body.task_index].status = 'done';
        tab.tasks[body.task_index].dismissed_by = 'operator';
        queue.last_updated = new Date().toISOString().slice(0, 10);
        queue.last_updated_by = 'operator';
        fs.writeFileSync(queueFile, JSON.stringify(queue, null, 2));
      }
    } catch {}
    sendJSON(res, { success: true });
    return;
  }

  // ===== PROPOSALS ROUTES =====

  // POST /api/proposals — create a proposal from an agent
  if (pathname === '/api/proposals' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const proposalsFile = path.join(DATA_DIR, 'proposals.json');
    let proposals = [];
    try { proposals = JSON.parse(fs.readFileSync(proposalsFile, 'utf8')); } catch {}
    const proposal = {
      id: 'prop-' + Date.now(),
      agent: body.agent || 'unknown',
      type: body.type || 'improvement',
      title: body.title || '',
      description: body.description || '',
      impact: body.impact || '',
      cost: body.cost || 'low',
      status: 'pending',
      created_at: Date.now(),
      resolved_at: null,
      resolved_by: null,
    };
    proposals.unshift(proposal);
    if (proposals.length > 50) proposals = proposals.slice(0, 50);
    fs.writeFileSync(proposalsFile, JSON.stringify(proposals, null, 2));
    sendJSON(res, { success: true, id: proposal.id });
    return;
  }

  // GET /api/proposals — list proposals
  if (pathname === '/api/proposals' && req.method === 'GET') {
    const proposalsFile = path.join(DATA_DIR, 'proposals.json');
    let proposals = [];
    try { proposals = JSON.parse(fs.readFileSync(proposalsFile, 'utf8')); } catch {}
    const statusFilter = url.searchParams?.get('status') || new URL('http://x' + req.url).searchParams.get('status');
    if (statusFilter) proposals = proposals.filter(p => p.status === statusFilter);
    sendJSON(res, proposals);
    return;
  }

  // POST /api/proposals/:id/approve — approve a proposal
  if (pathname.startsWith('/api/proposals/') && pathname.endsWith('/approve') && req.method === 'POST') {
    const id = pathname.replace('/api/proposals/', '').replace('/approve', '');
    const proposalsFile = path.join(DATA_DIR, 'proposals.json');
    let proposals = [];
    try { proposals = JSON.parse(fs.readFileSync(proposalsFile, 'utf8')); } catch {}
    const entry = proposals.find(p => p.id === id);
    if (!entry) { sendJSON(res, { error: 'Not found' }, 404); return; }
    entry.status = 'approved';
    entry.resolved_at = Date.now();
    entry.resolved_by = 'operator';
    fs.writeFileSync(proposalsFile, JSON.stringify(proposals, null, 2));
    sendJSON(res, { success: true, title: entry.title });
    return;
  }

  // POST /api/proposals/:id/reject — reject a proposal
  if (pathname.startsWith('/api/proposals/') && pathname.endsWith('/reject') && req.method === 'POST') {
    const id = pathname.replace('/api/proposals/', '').replace('/reject', '');
    const proposalsFile = path.join(DATA_DIR, 'proposals.json');
    let proposals = [];
    try { proposals = JSON.parse(fs.readFileSync(proposalsFile, 'utf8')); } catch {}
    const entry = proposals.find(p => p.id === id);
    if (!entry) { sendJSON(res, { error: 'Not found' }, 404); return; }
    entry.status = 'rejected';
    entry.resolved_at = Date.now();
    entry.resolved_by = 'operator';
    fs.writeFileSync(proposalsFile, JSON.stringify(proposals, null, 2));
    sendJSON(res, { success: true });
    return;
  }

  // GET /api/daily-plan — read today's plan
  if (pathname === '/api/daily-plan' && req.method === 'GET') {
    const planFile = path.join(DATA_DIR, 'daily-plan.json');
    try { sendJSON(res, JSON.parse(fs.readFileSync(planFile, 'utf8'))); }
    catch { sendJSON(res, { summary: 'No plan yet' }); }
    return;
  }

  // GET /api/agent-skills — read agent skill metrics + Claude skills from .md files
  if (pathname === '/api/agent-skills' && req.method === 'GET') {
    const skillsFile = path.join(DATA_DIR, 'agent-skills.json');
    let data = {};
    try { data = JSON.parse(fs.readFileSync(skillsFile, 'utf8')); } catch {}
    // Parse Claude skills from agent .md files
    const agentsDir = path.join(__dirname, '../../storyengine/agents');
    const agentIds = ['orchestrator', 'backend-dev', 'frontend-dev', 'qa-engineer', 'pipeline-tester'];
    for (const id of agentIds) {
      try {
        const md = fs.readFileSync(path.join(agentsDir, id + '.md'), 'utf8');
        const skills = [];
        const matches = md.matchAll(/\| `([^`]+)` \| (.+?) \| (.+?) \|/g);
        for (const m of matches) { skills.push({ name: m[1], when: m[2].trim(), what: m[3].trim() }); }
        if (!data.agents) data.agents = {};
        if (!data.agents[id]) data.agents[id] = {};
        data.agents[id].claude_skills = skills;
      } catch {}
    }
    sendJSON(res, data);
    return;
  }

  // GET /api/agent-instructions/:id — read agent .md file
  // Supports ?source=roles to read from agents/roles/ instead of storyengine/agents/
  if (pathname.startsWith('/api/agent-instructions/') && req.method === 'GET') {
    const agentId = decodeURIComponent(pathname.replace('/api/agent-instructions/', ''));
    if (agentId.includes('..') || agentId.includes('/')) { sendJSON(res, { error: 'Invalid agent ID' }, 400); return; }
    const url = new URL(req.url, `http://localhost:${PORT}`);
    const source = url.searchParams.get('source');
    const baseDir = source === 'roles'
      ? path.join(__dirname, '../../agents/roles')
      : path.join(__dirname, '../../storyengine/agents');
    const agentFile = path.join(baseDir, agentId + '.md');
    const resolved = path.resolve(agentFile);
    if (!resolved.startsWith(path.resolve(baseDir))) { sendJSON(res, { error: 'Invalid path' }, 400); return; }
    try { sendJSON(res, { id: agentId, source: source || 'storyengine', content: fs.readFileSync(resolved, 'utf8') }); }
    catch { sendJSON(res, { error: 'Agent file not found' }, 404); }
    return;
  }

  // PUT /api/agent-instructions/:id — write agent .md file
  if (pathname.startsWith('/api/agent-instructions/') && req.method === 'PUT') {
    const agentId = decodeURIComponent(pathname.replace('/api/agent-instructions/', ''));
    if (agentId.includes('..') || agentId.includes('/')) { sendJSON(res, { error: 'Invalid agent ID' }, 400); return; }
    const url = new URL(req.url, `http://localhost:${PORT}`);
    const source = url.searchParams.get('source');
    const baseDir = source === 'roles'
      ? path.join(__dirname, '../../agents/roles')
      : path.join(__dirname, '../../storyengine/agents');
    const agentFile = path.join(baseDir, agentId + '.md');
    const resolved = path.resolve(agentFile);
    if (!resolved.startsWith(path.resolve(baseDir))) { sendJSON(res, { error: 'Invalid path' }, 400); return; }
    let body = '';
    req.on('data', chunk => { body += chunk; });
    req.on('end', () => {
      try {
        const { content } = JSON.parse(body);
        if (typeof content !== 'string') { sendJSON(res, { error: 'content must be a string' }, 400); return; }
        fs.writeFileSync(resolved, content);
        sendJSON(res, { ok: true });
      } catch (e) { sendJSON(res, { error: e.message }, 500); }
    });
    return;
  }

  // GET /api/team-roles — list all role .md files from agents/roles/
  if (pathname === '/api/team-roles' && req.method === 'GET') {
    const rolesDir = path.join(__dirname, '../../agents/roles');
    try {
      const files = fs.readdirSync(rolesDir).filter(f => f.endsWith('.md'));
      const roles = files.map(f => {
        const id = f.replace('.md', '');
        const content = fs.readFileSync(path.join(rolesDir, f), 'utf8');
        const titleMatch = content.match(/^#\s+(.+)/m);
        return { id, name: titleMatch ? titleMatch[1] : id, file: f };
      });
      sendJSON(res, { roles, teamConfig: path.join(__dirname, '../../agents/TEAM.md') });
    } catch { sendJSON(res, { roles: [] }); }
    return;
  }

  // ===== COMMAND CENTER ROUTES =====

  // POST /api/deploy-prd — write PRD, decompose, set focus, spawn agents
  if (pathname === '/api/deploy-prd' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const agentsDir = path.join(__dirname, '../../agents');
    const prdPath = path.join(agentsDir, 'prd.md');
    if (!body.content || typeof body.content !== 'string') { sendJSON(res, { error: 'content required' }, 400); return; }
    // Clear stale PRD files BEFORE deploying (prevents false completion detection from old progress.md)
    for (const f of ['prd.json', 'progress.md']) {
      try { fs.unlinkSync(path.join(agentsDir, f)); } catch {}
    }
    fs.writeFileSync(prdPath, body.content);
    const projectRoot = path.resolve(__dirname, '../../');
    // Chain: decompose → set focus → spawn agents for each role
    exec(`cd "${projectRoot}" && CLAUDE_BIN="${CLAUDE_BIN}" bash agents/decompose.sh agents/prd.md > /tmp/decompose.log 2>&1`, {
      timeout: 1200000, maxBuffer: 10 * 1024 * 1024,
      env: { ...process.env, HOME: process.env.HOME || require('os').homedir(), PATH: `${process.env.PATH}:${path.join(process.env.HOME || require('os').homedir(), '.npm-global/bin')}` }
    }, (err) => {
      if (err) {
        const msg = err.killed ? 'Decomposition timed out after 20 minutes' : `Decompose failed: ${err.message.substring(0, 200)}`;
        console.error(msg);
        // Write error state so frontend can detect failure and offer retry
        try { fs.writeFileSync(path.join(agentsDir, 'prd.json'), JSON.stringify({ error: true, message: msg, timestamp: Date.now() })); } catch {}
        return;
      }
      console.log('PRD decomposition complete — boosting cadence, setting focus, spawning agents');
      // Auto-cadence: save current cadence and boost to max for PRD execution
      try {
        const ctrlFile = path.join(DATA_DIR, 'controls.json');
        let ctrl = {};
        try { ctrl = JSON.parse(fs.readFileSync(ctrlFile, 'utf8')); } catch {}
        if (ctrl.cadence !== PRD_BOOST_CADENCE) {
          ctrl.pre_prd_cadence = ctrl.cadence || 'light';
          fs.writeFileSync(ctrlFile, JSON.stringify(ctrl, null, 2));
          setCadence(PRD_BOOST_CADENCE);
          console.log(`Auto-cadence: boosted from ${ctrl.pre_prd_cadence} to ${PRD_BOOST_CADENCE}`);
        }
      } catch (e) { console.error('Auto-cadence boost failed:', e.message); }
      try {
        const prd = JSON.parse(fs.readFileSync(path.join(agentsDir, 'prd.json'), 'utf8'));
        const title = prd.title || 'PRD Mission';
        // Stamp deploy time so completion detection enforces minimum execution time
        prd._deployed_at = new Date().toISOString();
        fs.writeFileSync(path.join(agentsDir, 'prd.json'), JSON.stringify(prd, null, 2));
        // Write decomposed tasks into task-queue.json so they appear in the Queue UI
        try {
          const tqPath = path.join(projectRoot, 'storyengine/agents/task-queue.json');
          let tq = {};
          try { tq = JSON.parse(fs.readFileSync(tqPath, 'utf8')); } catch {}
          if (!tq.tabs) tq.tabs = [];
          const newTab = {
            id: tq.tabs.length + 1,
            name: title,
            status: 'active',
            created_at: new Date().toISOString(),
            tasks: (prd.tasks || []).map((t, i) => ({
              id: `${tq.tabs.length + 1}-${i + 1}`,
              description: t.title || t.description || `Task ${i + 1}`,
              role: t.role || 'backend',
              status: 'pending',
              depends_on: t.depends_on || [],
              acceptance_criteria: t.acceptance_criteria || ''
            }))
          };
          tq.tabs.push(newTab);
          tq.current_tab = newTab.id;
          tq.last_updated = new Date().toISOString();
          tq.last_updated_by = 'prd-deploy';
          fs.writeFileSync(tqPath, JSON.stringify(tq, null, 2));
          console.log(`Task queue: added tab "${title}" with ${newTab.tasks.length} tasks`);
        } catch (e) { console.error('Task queue write failed:', e.message); }
        // Set focus directive so all agents prioritize PRD work
        const controlsFile = path.join(projectRoot, 'storyengine/agents/controls.json');
        let controls = {};
        try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
        controls.focus = `PRD deployed: ${title}. Execute all PRD tasks from agents/prd.json.`;
        fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
        // Spawn unified agents (run-agent.sh) — they auto-detect PRD and work on it
        const roleToAgent = { backend: 'backend-dev', frontend: 'frontend-dev', qa: 'qa-engineer', 'pipeline-tester': 'pipeline-tester', security: 'security-auditor' };
        const roles = [...new Set((prd.tasks || []).map(t => t.role).filter(Boolean))];
        for (const role of roles) {
          const agent = roleToAgent[role] || role;
          exec(`cd "${projectRoot}/storyengine/agents" && CLAUDE_BIN="${CLAUDE_BIN}" bash run-agent.sh "${agent}" > /tmp/prd-${agent}.log 2>&1`,
            (e) => { if (e) console.error(`Spawn ${agent} failed:`, e.message); else console.log(`Agent ${agent} started`); });
        }
      } catch (e) { console.error('Post-decompose spawn failed:', e.message); }
    });
    sendJSON(res, { success: true, message: 'Decomposing PRD and preparing agents...' });
    return;
  }

  // GET /api/mission-status — current mission state from prd.json + progress.md
  if (pathname === '/api/mission-status' && req.method === 'GET') {
    const agentsDir = path.join(__dirname, '../../agents');
    const prdPath = path.join(agentsDir, 'prd.json');
    const progressPath = path.join(agentsDir, 'progress.md');
    const prdMdPath = path.join(agentsDir, 'prd.md');
    let prd = null, progress = '', prdRaw = '';
    try { prd = JSON.parse(fs.readFileSync(prdPath, 'utf8')); } catch {}
    try { progress = fs.readFileSync(progressPath, 'utf8'); } catch {}
    try { prdRaw = fs.readFileSync(prdMdPath, 'utf8'); } catch {}
    if (!prd && !prdRaw) { sendJSON(res, { active: false }); return; }
    if (!prd && prdRaw) { sendJSON(res, { active: true, decomposing: true, title: 'Decomposing...' }); return; }
    // Detect decompose failure (error prd.json written by timeout/crash handler)
    if (prd && prd.error) { sendJSON(res, { active: true, error: true, errorMessage: prd.message || 'Decomposition failed', hasPrdMd: !!prdRaw }); return; }
    const total = prd.tasks?.length || 0;
    // Build task status from prd.json tasks + progress.md completion markers
    // progress.md may contain stale entries from previous PRDs, so cross-reference with prd.json task IDs
    const prdTaskIds = new Set((prd.tasks || []).map(t => t.id));
    const doneIdsFromProgress = new Set();
    const blockedIdsFromProgress = new Set();
    for (const line of progress.split('\n')) {
      const m = line.match(/- \[x\]\s*(?:T)?(\d+)[.:]/i);
      if (m && prdTaskIds.has(parseInt(m[1]))) doneIdsFromProgress.add(parseInt(m[1]));
      if (line.includes('BLOCKED') && m && prdTaskIds.has(parseInt(m[1]))) blockedIdsFromProgress.add(parseInt(m[1]));
    }
    // Use progress.md done count if available, otherwise fall back to prd.json status field
    const doneFromPrdJson = (prd.tasks || []).filter(t => t.status === 'done' || t.status === 'verified').length;
    const done = doneIdsFromProgress.size || doneFromPrdJson;
    const blocked = blockedIdsFromProgress.size || (prd.tasks || []).filter(t => t.status === 'blocked').length;
    const inProgress = Math.max(0, total - done - blocked);
    // Build tasks array for frontend rendering (from prd.json, enriched with progress.md status)
    const tasks = (prd.tasks || []).map(t => ({
      id: t.id, title: t.title, role: t.role,
      status: doneIdsFromProgress.has(t.id) ? 'done' : blockedIdsFromProgress.has(t.id) ? 'blocked' : (t.status === 'done' || t.status === 'verified') ? 'done' : t.status || 'pending',
      depends_on: t.depends_on || [], acceptance_criteria: t.acceptance_criteria || []
    }));
    // Auto-sync PRD tasks into task-queue.json so they appear in the Queue UI
    // This ensures tasks are visible even if the deploy callback failed (e.g. server crash)
    try {
      const tqPath = path.join(__dirname, '../../storyengine/agents/task-queue.json');
      let tq = {};
      try { tq = JSON.parse(fs.readFileSync(tqPath, 'utf8')); } catch {}
      if (!tq.tabs) tq.tabs = [];
      // Find existing tab for this PRD (by title match) or create one
      const prdTabName = prd.title || 'Active PRD';
      let prdTab = tq.tabs.find(t => t.name === prdTabName);
      if (!prdTab) {
        prdTab = { id: tq.tabs.length + 1, name: prdTabName, status: 'active', created_at: new Date().toISOString(), tasks: [] };
        tq.tabs.push(prdTab);
      }
      // Sync task statuses from prd.json → task-queue.json
      prdTab.tasks = tasks.map((t, i) => ({
        id: `PRD-${t.id}`,
        description: t.title,
        role: t.role || 'backend',
        status: t.status,
        depends_on: t.depends_on || [],
        verified: t.status === 'done'
      }));
      prdTab.status = tasks.every(t => t.status === 'done') ? 'complete' : 'active';
      tq.last_updated = new Date().toISOString();
      tq.last_updated_by = 'mission-sync';
      fs.writeFileSync(tqPath, JSON.stringify(tq, null, 2));
    } catch (e) { /* silent — task queue sync is best-effort */ }

    // Enforce minimum execution time — agents from previous PRD write stale [x] marks
    const deployedAt = prd._deployed_at ? new Date(prd._deployed_at).getTime() : 0;
    const MIN_EXECUTION_MS = 5 * 60 * 1000; // 5 minutes minimum before completion allowed
    const elapsed = Date.now() - deployedAt;
    const canComplete = deployedAt > 0 && elapsed >= MIN_EXECUTION_MS;
    // Auto-cascade: when PRD completes, check queue for next PRD
    if (total > 0 && done >= total && canComplete) {
      const q = readPrdQueue();
      const hasNext = q.current_index >= 0 && q.current_index < q.queue.length - 1;
      if (hasNext) {
        // Mark current PRD as completed in queue
        if (q.queue[q.current_index]) {
          q.queue[q.current_index].completed_at = new Date().toISOString();
          q.deployed.push({ title: prd.title, completed_at: new Date().toISOString() });
          writePrdQueue(q);
        }
        // Clean current PRD files before deploying next
        const agentsDirLocal = path.join(__dirname, '../../agents');
        for (const f of ['prd.json', 'prd.md', 'progress.md']) {
          try { fs.unlinkSync(path.join(agentsDirLocal, f)); } catch {}
        }
        console.log(`PRD Queue: "${prd.title}" complete — deploying next PRD...`);
        // Small delay to let cleanup settle, then deploy next
        setTimeout(() => deployNextPrd(), 5000);
        sendJSON(res, { active: true, decomposing: false, title: prd.title || 'Untitled', total, done, blocked, inProgress, progress, tasks, queueNext: true });
        return;
      }
      // No queue or queue exhausted — restore cadence as before
      try {
        const ctrlFile = path.join(DATA_DIR, 'controls.json');
        const ctrl = JSON.parse(fs.readFileSync(ctrlFile, 'utf8'));
        if (ctrl.pre_prd_cadence && ctrl.cadence !== ctrl.pre_prd_cadence) {
          const restored = ctrl.pre_prd_cadence;
          delete ctrl.pre_prd_cadence;
          fs.writeFileSync(ctrlFile, JSON.stringify(ctrl, null, 2));
          setCadence(restored);
          console.log(`Auto-cadence: PRD complete, restored to ${restored}`);
        }
      } catch {}
    }
    sendJSON(res, { active: true, decomposing: false, title: prd.title || 'Untitled', total, done, blocked, inProgress, progress, tasks });
    return;
  }

  // GET /api/recover-prd — read prd.md from disk so frontend can recover after failure
  if (pathname === '/api/recover-prd' && req.method === 'GET') {
    const prdMdPath = path.join(__dirname, '../../agents/prd.md');
    try {
      const content = fs.readFileSync(prdMdPath, 'utf8');
      sendJSON(res, { content });
    } catch { sendJSON(res, { content: '' }); }
    return;
  }

  // DELETE /api/mission — clear current mission + focus directive + user-browser errors
  if (pathname === '/api/mission' && req.method === 'DELETE') {
    const agentsDir = path.join(__dirname, '../../agents');
    for (const f of ['prd.json', 'prd.md', 'progress.md']) {
      try { fs.unlinkSync(path.join(agentsDir, f)); } catch {}
    }
    // Also clear focus directive (PRD sets focus on deploy, so clear on mission clear)
    const controlsFile = path.join(DATA_DIR, 'controls.json');
    try {
      const controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8'));
      delete controls.focus;
      fs.writeFileSync(controlsFile, JSON.stringify(controls, null, 2));
    } catch {}
    // Clear user-browser errors from activity log
    const activityFile = path.join(DATA_DIR, 'activity-log.json');
    try {
      const logs = JSON.parse(fs.readFileSync(activityFile, 'utf8'));
      const filtered = logs.filter(e => !(e.agent === 'user-browser' && e.status === 'error'));
      fs.writeFileSync(activityFile, JSON.stringify(filtered, null, 2));
    } catch {}
    // Clear error tracker
    try { fs.unlinkSync('/tmp/prd-watcher-errors-seen.txt'); } catch {}
    sendJSON(res, { success: true });
    return;
  }

  // ─── PRD Queue Endpoints ──────────────────────────────────────────────────

  // POST /api/prd-queue — add PRDs to the queue (accepts array of {title, content})
  if (pathname === '/api/prd-queue' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const prds = body.prds || (body.content ? [{ title: body.title || 'Untitled', content: body.content }] : []);
    if (!prds.length) { sendJSON(res, { error: 'prds array required (each with title + content)' }, 400); return; }
    const q = readPrdQueue();
    for (const p of prds) {
      q.queue.push({ title: p.title, content: p.content, queued_at: new Date().toISOString() });
    }
    writePrdQueue(q);
    sendJSON(res, { success: true, queued: prds.length, total: q.queue.length, message: `${prds.length} PRD(s) added to queue` });
    return;
  }

  // GET /api/prd-queue — view queue status
  if (pathname === '/api/prd-queue' && req.method === 'GET') {
    const q = readPrdQueue();
    const items = q.queue.map((p, i) => ({
      index: i, title: p.title, queued_at: p.queued_at,
      started_at: p.started_at || null, completed_at: p.completed_at || null,
      status: p.completed_at ? 'completed' : p.started_at ? 'active' : 'queued'
    }));
    sendJSON(res, { total: q.queue.length, current_index: q.current_index, deployed: q.deployed.length, items });
    return;
  }

  // POST /api/prd-queue/start — start executing the queue (deploys first PRD)
  if (pathname === '/api/prd-queue/start' && req.method === 'POST') {
    const q = readPrdQueue();
    if (!q.queue.length) { sendJSON(res, { error: 'Queue is empty' }, 400); return; }
    if (q.current_index >= 0 && q.current_index < q.queue.length) {
      const current = q.queue[q.current_index];
      if (current.started_at && !current.completed_at) {
        sendJSON(res, { error: `PRD "${current.title}" is already running` }, 409); return;
      }
    }
    // Reset index to -1 so deployNextPrd starts at 0
    q.current_index = -1;
    writePrdQueue(q);
    deployNextPrd();
    sendJSON(res, { success: true, message: `Starting queue — deploying "${q.queue[0].title}"` });
    return;
  }

  // GET /api/prd-queue/:index — get full PRD content for a queue item
  if (pathname.match(/^\/api\/prd-queue\/\d+$/) && req.method === 'GET') {
    const idx = parseInt(pathname.split('/').pop());
    const q = readPrdQueue();
    if (idx < 0 || idx >= q.queue.length) { sendJSON(res, { error: 'Not found' }, 404); return; }
    sendJSON(res, { index: idx, title: q.queue[idx].title, content: q.queue[idx].content });
    return;
  }

  // PUT /api/prd-queue/:index — update PRD content for a queue item
  if (pathname.match(/^\/api\/prd-queue\/\d+$/) && req.method === 'PUT') {
    const idx = parseInt(pathname.split('/').pop());
    const body = JSON.parse(await readBody(req));
    const q = readPrdQueue();
    if (idx < 0 || idx >= q.queue.length) { sendJSON(res, { error: 'Not found' }, 404); return; }
    if (body.title) q.queue[idx].title = body.title;
    if (body.content) q.queue[idx].content = body.content;
    writePrdQueue(q);
    sendJSON(res, { success: true, message: `PRD ${idx + 1} updated` });
    return;
  }

  // DELETE /api/prd-queue — clear the entire queue
  if (pathname === '/api/prd-queue' && req.method === 'DELETE') {
    writePrdQueue({ queue: [], deployed: [], current_index: -1 });
    sendJSON(res, { success: true, message: 'Queue cleared' });
    return;
  }

  // POST /api/generate-prd — Claude Opus generates structured PRD from rough notes
  if (pathname === '/api/generate-prd' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    if (!body.content || typeof body.content !== 'string') { sendJSON(res, { error: 'content required' }, 400); return; }
    const taskId = 'prd-' + Date.now();
    const resultFile = path.join(DATA_DIR, taskId + '.json');
    fs.writeFileSync(resultFile, JSON.stringify({ status: 'generating' }));
    const promptFile = `/tmp/${taskId}-prompt.txt`;
    const prompt = `You are a senior technical product manager writing a PRD for an autonomous dev team.

The user typed rough notes about what they want built. Transform these into a structured, actionable PRD.

## User's Notes
${body.content}

## Output Format — write ONLY this markdown, no preamble:

# PRD: [Clear Title]

## Summary
[2-3 sentences: what we're building, why, and the expected outcome]

## Requirements
[Numbered list of specific, concrete requirements. Be PRECISE — "email/password auth with bcrypt, JWT tokens, httpOnly cookies" not just "auth system"]

## Pages / UI
[List each page/screen with what it shows and what actions are available]

## API Endpoints
[List each endpoint: METHOD /path — description, request body, response shape]

## Database Changes
[Any new tables, columns, or migrations needed]

## Acceptance Criteria
[Numbered list of machine-verifiable criteria. Each MUST be testable with: curl, tsc --noEmit, Playwright, test -f, or psql]

## Execution Order
[Which tasks must happen first (bottom-up: database → backend → frontend → QA)]

## Agent Assignments
IMPORTANT: You may ONLY assign tasks to these 4 roles. No other roles exist:
- **backend** (role: "backend"): Python/FastAPI, database migrations, API endpoints
- **frontend** (role: "frontend"): React/Next.js, TypeScript, UI components, pages
- **qa** (role: "qa"): Playwright browser testing, acceptance criteria verification, bug filing
- **pipeline-tester** (role: "pipeline-tester"): Opens every page, clicks every button, finds bugs

Do NOT create tasks for "security", "lead", "devops", or any other role. Security checks should be part of the QA agent's verification tasks.

## Testing Strategy
The Pipeline Tester and QA agents MUST:
- Open every affected page in a real browser (Playwright)
- Click every button and verify the result
- Check for console errors on every page
- File specific bug reports with reproduction steps for any failures
- Include security checks: auth validation, input sanitization, no data leaks

RULES:
- Be SPECIFIC and CONCRETE. Vague requirements create vague implementations.
- Every acceptance criterion must be a shell command that exits 0 on success.
- Think about error states, empty states, loading states, and edge cases.
- Security checks go in QA tasks, NOT a separate security role.
- Testing is NOT optional — QA and Pipeline Tester tasks are required in every PRD.
- The "role" field in tasks MUST be one of: "backend", "frontend", "qa", "pipeline-tester".
- Output ONLY the PRD markdown. No commentary before or after.`;
    fs.writeFileSync(promptFile, prompt);
    // Run wrapper script in background — handles Claude CLI + writes result JSON
    const scriptPath = path.resolve(__dirname, '../../agents/generate-prd.sh');
    exec(`CLAUDE_BIN="${CLAUDE_BIN}" bash "${scriptPath}" "${promptFile}" "${resultFile}"`, {
      timeout: 600000, maxBuffer: 5 * 1024 * 1024,
      env: { ...process.env, HOME: process.env.HOME || require('os').homedir(), PATH: `${process.env.PATH}:${path.join(process.env.HOME || require('os').homedir(), '.npm-global/bin')}` }
    }, (err) => {
      try { fs.unlinkSync(promptFile); } catch {}
      if (err && !fs.existsSync(resultFile)) {
        console.error('generate-prd script failed:', err.message);
        fs.writeFileSync(resultFile, JSON.stringify({ status: 'error', error: err.message.substring(0, 300) }));
      }
    });
    sendJSON(res, { taskId });
    return;
  }

  // GET /api/generate-prd/:taskId — poll for PRD generation result
  if (pathname.startsWith('/api/generate-prd/') && req.method === 'GET') {
    const taskId = pathname.split('/').pop();
    if (!taskId || !/^prd-\d+$/.test(taskId)) { sendJSON(res, { error: 'invalid taskId' }, 400); return; }
    const resultFile = path.join(DATA_DIR, taskId + '.json');
    try {
      const data = JSON.parse(fs.readFileSync(resultFile, 'utf8'));
      if (data.status === 'done' || data.status === 'error') {
        try { fs.unlinkSync(resultFile); } catch {} // cleanup after read
      }
      sendJSON(res, data);
    } catch { sendJSON(res, { status: 'not_found' }, 404); }
    return;
  }

  // POST /api/spawn-agent — run an agent immediately (no cron wait)
  // Pass force:true to bypass the kill switch (used by Telegram bot for one-shot runs)
  // Pass one_shot:true to auto-disable team after the agent finishes
  if (pathname === '/api/spawn-agent' && req.method === 'POST') {
    const body = JSON.parse(await readBody(req));
    const { role, system, force, one_shot } = body;
    if (!role) { sendJSON(res, { error: 'role required' }, 400); return; }
    // Respect kill switch — unless force:true (Telegram operator override)
    if (!force) {
      try {
        const controls = JSON.parse(fs.readFileSync(path.join(DATA_DIR, 'controls.json'), 'utf8'));
        if (controls.team_enabled === false) {
          sendJSON(res, { success: false, message: `Team is OFF — ${role} not spawned. Use force:true to override.` });
          return;
        }
      } catch {}
    }
    // If force-spawning while team is off, temporarily enable for this run
    const controlsPath = path.join(DATA_DIR, 'controls.json');
    let wasOff = false;
    if (force) {
      try {
        const controls = JSON.parse(fs.readFileSync(controlsPath, 'utf8'));
        wasOff = controls.team_enabled === false;
        if (wasOff) {
          controls.team_enabled = true;
          writeFileSync(controlsPath, JSON.stringify(controls, null, 2));
        }
      } catch {}
    }
    const projectRoot = path.resolve(__dirname, '../../');
    exec(`cd "${projectRoot}/storyengine/agents" && CLAUDE_BIN="${CLAUDE_BIN}" bash run-agent.sh "${role}" > /tmp/prd-${role}.log 2>&1`,
      (err) => {
        if (err) console.error(`Agent ${role} failed:`, err.message);
        // One-shot mode: re-disable team after agent finishes
        if (one_shot || (force && wasOff)) {
          try {
            const controls = JSON.parse(fs.readFileSync(controlsPath, 'utf8'));
            controls.team_enabled = false;
            writeFileSync(controlsPath, JSON.stringify(controls, null, 2));
          } catch {}
        }
      });
    sendJSON(res, { success: true, message: `Spawned ${role}${force ? ' (forced)' : ''}${one_shot || (force && wasOff) ? ' — will auto-disable team when done' : ''}` });
    return;
  }

  // GET /api/retros — read latest retrospective
  if (pathname === '/api/retros' && req.method === 'GET') {
    const retroFile = path.join(DATA_DIR, 'retro.json');
    try { sendJSON(res, JSON.parse(fs.readFileSync(retroFile, 'utf8'))); }
    catch { sendJSON(res, { summary: 'No retro yet', history: [] }); }
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
      try {
        let jobs = loadCrons();
        // Feature 5: Enrich with live controls state
        const controlsFile = path.join(DATA_DIR, 'controls.json');
        let controls = {};
        try { controls = JSON.parse(fs.readFileSync(controlsFile, 'utf8')); } catch {}
        const teamOff = controls.team_enabled === false;
        const paused = controls.paused_agents || [];
        const cronToAgent = {
          'backend-dev': 'backend-dev', 'frontend-dev': 'frontend-dev',
          'qa-engineer': 'qa-engineer', 'security-auditor': 'security-auditor',
          'pipeline-tester': 'pipeline-tester', 'orchestrator-micro': 'orchestrator',
          'orchestrator-grand': 'orchestrator',
        };
        jobs = jobs.map(j => ({
          ...j,
          effectivelyEnabled: !teamOff && j.enabled && !paused.includes(cronToAgent[j.id] || ''),
          teamOff,
          agentPaused: paused.includes(cronToAgent[j.id] || ''),
        }));
        sendJSON(res, jobs);
      } catch (err) { sendJSON(res, { error: 'Could not read cron jobs', message: err.message }, 500); }
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

const HOST = process.env.HOST || '0.0.0.0';
server.listen(PORT, HOST, () => {
  console.log(`\n  Rubric Console`);
  console.log(`  http://localhost:${PORT}`);
  console.log(`  Templates active: ${INSTALLED_TABS.join(', ')}\n`);
});
