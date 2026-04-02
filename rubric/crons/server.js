import { createServer } from 'node:http';
import { readFileSync, existsSync } from 'node:fs';
import { join, dirname, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '5050', 10);
const HOST = '127.0.0.1';

// Load config
const configPath = join(__dirname, 'config.json');
const config = existsSync(configPath)
  ? JSON.parse(readFileSync(configPath, 'utf8'))
  : { cronPaths: ['./data/crons.json'], timezone: 'auto' };

const MIME = {
  '.html': 'text/html',
  '.js': 'application/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
};

function sendJSON(res, data, status = 200) {
  res.writeHead(status, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify(data));
}

function loadCrons() {
  const allJobs = [];
  const paths = config.cronPaths || ['./data/crons.json'];

  for (const p of paths) {
    const fullPath = p.startsWith('/') || p.match(/^[A-Z]:\\/)
      ? p
      : join(__dirname, p);

    if (!existsSync(fullPath)) continue;

    try {
      const raw = JSON.parse(readFileSync(fullPath, 'utf8'));

      // Support: array of jobs, {jobs: [...]}, {crons: [...]}
      let jobsArr;
      if (Array.isArray(raw)) {
        jobsArr = raw;
      } else if (raw.jobs) {
        jobsArr = raw.jobs;
      } else if (raw.crons) {
        jobsArr = raw.crons;
      } else {
        continue;
      }

      for (let i = 0; i < jobsArr.length; i++) {
        const j = jobsArr[i];
        // Normalize: support "schedule" (string or {expr, tz}) or "cron" field
        let expr, tz;
        if (typeof j.schedule === 'string') {
          expr = j.schedule;
          tz = j.tz || config.timezone || 'auto';
        } else if (j.schedule && j.schedule.expr) {
          expr = j.schedule.expr;
          tz = j.schedule.tz || config.timezone || 'auto';
        } else if (j.cron) {
          expr = j.cron;
          tz = j.tz || config.timezone || 'auto';
        } else {
          continue; // skip entries without a cron expression
        }

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
    } catch (err) {
      console.error(`Failed to read cron file ${fullPath}:`, err.message);
    }
  }

  return allJobs;
}

const server = createServer((req, res) => {
  const url = new URL(req.url, `http://${HOST}:${PORT}`);
  const pathname = url.pathname;

  // API: GET /api/crons
  if (pathname === '/api/crons' && req.method === 'GET') {
    try {
      const jobs = loadCrons();
      sendJSON(res, jobs);
    } catch (err) {
      sendJSON(res, { error: 'Could not read cron jobs', message: err.message }, 500);
    }
    return;
  }

  // API: GET /api/config (brand name, timezone)
  if (pathname === '/api/config' && req.method === 'GET') {
    sendJSON(res, {
      brandName: config.brandName || 'RUBRIC Crons',
      timezone: config.timezone || 'auto',
    });
    return;
  }

  // Static files
  let filePath;
  if (pathname === '/' || pathname === '/index.html') {
    filePath = join(__dirname, 'index.html');
  } else if (pathname === '/icons.html') {
    filePath = join(__dirname, 'icons.html');
  } else {
    res.writeHead(404);
    res.end('Not found');
    return;
  }

  if (!existsSync(filePath)) {
    res.writeHead(404);
    res.end('Not found');
    return;
  }

  const ext = extname(filePath);
  const mime = MIME[ext] || 'application/octet-stream';
  res.writeHead(200, { 'Content-Type': mime });
  res.end(readFileSync(filePath));
});

server.listen(PORT, HOST, () => {
  console.log(`RUBRIC Crons running at http://${HOST}:${PORT}`);
});
