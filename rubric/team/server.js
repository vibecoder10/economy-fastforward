import { createServer } from 'node:http';
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import { join, resolve, basename, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '5050', 10);

// Load config
const config = JSON.parse(readFileSync(join(__dirname, 'config.json'), 'utf8'));

// Scan for skill files in a directory tree
// Looks for directories containing SKILL.md (Claude Code convention)
function scanSkills(basePath) {
  const skills = [];
  if (!existsSync(basePath)) return skills;

  function walk(dir) {
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        // Check if this directory contains a SKILL.md
        const skillFile = join(fullPath, 'SKILL.md');
        if (existsSync(skillFile)) {
          skills.push(entry.name);
        }
        walk(fullPath);
      }
    }
  }
  walk(basePath);
  return skills;
}

// Map skills to agents by scanning their configured skillsPath
function getTeamSkills() {
  const skillsRoot = resolve(__dirname, config.skillsRoot || '../');
  const result = {};

  // Shared skills (e.g., .claude/skills/)
  const sharedPath = join(skillsRoot, '.claude', 'skills');
  const sharedSkills = scanSkills(sharedPath);

  // Lead agent gets shared skills
  result[config.lead.id] = [...sharedSkills];

  // Each sub-agent: scan agents/{id}/.claude/skills/
  for (const agent of config.agents) {
    const agentPath = join(skillsRoot, 'agents', agent.id.toUpperCase(), '.claude', 'skills');
    const agentSkills = scanSkills(agentPath);
    // Agent gets shared + agent-specific
    result[agent.id] = [...sharedSkills, ...agentSkills];
  }

  return result;
}

// Serve
const indexHtml = readFileSync(join(__dirname, 'index.html'), 'utf8');

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);

  if (url.pathname === '/api/team') {
    res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(config));
    return;
  }

  if (url.pathname === '/api/team/skills') {
    const skills = getTeamSkills();
    res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
    res.end(JSON.stringify(skills));
    return;
  }

  if (url.pathname === '/icons.html') {
    try {
      const icons = readFileSync(join(__dirname, 'icons.html'), 'utf8');
      res.writeHead(200, { 'Content-Type': 'text/html' });
      res.end(icons);
    } catch {
      res.writeHead(404);
      res.end('Not found');
    }
    return;
  }

  // Serve index.html for everything else
  res.writeHead(200, { 'Content-Type': 'text/html' });
  res.end(indexHtml);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`RUBRIC Team running at http://127.0.0.1:${PORT}`);
});
