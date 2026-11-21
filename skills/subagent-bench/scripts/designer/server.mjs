#!/usr/bin/env node
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

function parseArgs(argv) {
  const opts = {
    workDir: '/tmp/opencode/designer-bench',
    configs: null,
    basePort: 4200,
  };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--work-dir' && i + 1 < argv.length) {
      opts.workDir = argv[++i];
    } else if (arg === '--configs' && i + 1 < argv.length) {
      opts.configs = argv[++i];
    } else if (arg === '--base-port' && i + 1 < argv.length) {
      opts.basePort = Number(argv[++i]);
    } else if (arg === '--help' || arg === '-h') {
      console.log('Usage: server.mjs [--work-dir <dir>] [--configs <c1,c2,...>] [--base-port <num>]');
      process.exit(0);
    }
  }
  return opts;
}

function loadConfigs(workDir, configsFlag) {
  if (configsFlag) {
    const parsed = configsFlag.split(',').map((s) => s.trim()).filter(Boolean);
    if (parsed.length > 0) return parsed;
  }
  const configsPath = path.join(workDir, 'configs.json');
  if (!fs.existsSync(configsPath)) {
    console.error(`Error: --configs not provided and ${configsPath} not found.`);
    process.exit(1);
  }
  const raw = JSON.parse(fs.readFileSync(configsPath, 'utf-8'));
  const list = Array.isArray(raw) ? raw : Array.isArray(raw?.configs) ? raw.configs : [];
  const configs = list.map((item) => (typeof item === 'string' ? item : item?.configId || item?.id)).filter(Boolean);
  if (configs.length === 0) {
    console.error(`Error: no configs found in ${configsPath}.`);
    process.exit(1);
  }
  return configs;
}

const opts = parseArgs(process.argv);
const workDir = path.resolve(opts.workDir);
const runsBase = path.join(workDir, 'runs');
const configs = loadConfigs(workDir, opts.configs);
const basePort = Number.isFinite(opts.basePort) ? opts.basePort : 4200;

if (configs.length > 99) {
  console.error(`Error: max 99 configs supported per challenge block (got ${configs.length}).`);
  process.exit(1);
}

const CHALLENGES = [
  { name: 'd1-bughunt', offset: 1 },
  { name: 'd2-greenfield', offset: 101 },
  { name: 'd3-interactive', offset: 201 },
];

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.js': 'application/javascript; charset=utf-8',
  '.mjs': 'application/javascript; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.webp': 'image/webp',
  '.woff2': 'font/woff2',
};

const portMap = {};
const servers = [];

for (const ch of CHALLENGES) {
  portMap[ch.name] = {};
  configs.forEach((cfg, idx) => {
    const port = basePort + ch.offset + idx;
    const rootDir = path.resolve(runsBase, ch.name, cfg);
    portMap[ch.name][cfg] = port;

    const server = http.createServer((req, res) => {
      const urlPath = (req.url || '/').split('?')[0];
      const rel = urlPath === '/' ? 'index.html' : urlPath.replace(/^\/+/, '');
      const fullPath = path.resolve(rootDir, rel);
      if (fullPath !== rootDir && !fullPath.startsWith(rootDir + path.sep)) {
        res.writeHead(403);
        res.end('Forbidden');
        return;
      }
      fs.readFile(fullPath, (err, data) => {
        if (err) {
          res.writeHead(404);
          res.end('Not found: ' + rel);
          return;
        }
        const ext = path.extname(fullPath).toLowerCase();
        res.writeHead(200, {
          'Content-Type': MIME[ext] || 'application/octet-stream',
          'Cache-Control': 'no-store',
        });
        res.end(data);
      });
    });

    server.listen(port, '127.0.0.1');
    servers.push(server);
  });
}

fs.mkdirSync(workDir, { recursive: true });
const portsFile = path.join(workDir, 'ports.json');
const pidFile = path.join(workDir, 'server.pid');
fs.writeFileSync(portsFile, JSON.stringify(portMap, null, 2) + '\n');
fs.writeFileSync(pidFile, String(process.pid) + '\n');

const summary = CHALLENGES.map((ch) => {
  const first = basePort + ch.offset;
  const last = first + configs.length - 1;
  return first === last ? `${ch.name}:${first}` : `${ch.name}:${first}-${last}`;
}).join(', ');
console.log(`Designer bench servers ready on ${servers.length} ports (${summary}).`);

let shuttingDown = false;
function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  try {
    if (fs.existsSync(pidFile) && fs.readFileSync(pidFile, 'utf-8').trim() === String(process.pid)) {
      fs.unlinkSync(pidFile);
    }
  } catch {
    // ignore cleanup error
  }
  let remaining = servers.length;
  if (remaining === 0) process.exit(0);
  const timer = setTimeout(() => process.exit(0), 2000);
  timer.unref();
  for (const s of servers) {
    s.close(() => {
      remaining -= 1;
      if (remaining <= 0) process.exit(0);
    });
  }
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
