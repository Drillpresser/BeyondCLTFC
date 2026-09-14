// Local editor server for BeyondCLTFC — zero dependencies (Node built-ins only).
//
// Serves the wizard UI and a tiny API to read the dataset and write manual
// edits to data/overrides.json. Runs locally only; nothing here is deployed.
//
//   node editor/server.mjs          (or: npm run edit  from web/)
//
// Then open http://localhost:4321 . Saving writes data/overrides.json; the
// optional "Rebuild" button runs scripts/build_players.py to regenerate
// data/players.json so you can review the merged result before committing.

import http from "node:http";
import { readFile, writeFile, access } from "node:fs/promises";
import { constants } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { spawn } from "node:child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const DATA = path.join(ROOT, "data");
const SCRIPTS = path.join(ROOT, "scripts");
const PORT = Number(process.env.PORT) || 4321;

const exists = (p) => access(p, constants.F_OK).then(() => true).catch(() => false);

async function readJson(p, fallback) {
  try {
    return JSON.parse(await readFile(p, "utf8"));
  } catch {
    return fallback;
  }
}

function send(res, status, body, type = "application/json") {
  res.writeHead(status, { "Content-Type": type, "Cache-Control": "no-store" });
  res.end(typeof body === "string" ? body : JSON.stringify(body));
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = "";
    req.on("data", (c) => (data += c));
    req.on("end", () => resolve(data));
    req.on("error", reject);
  });
}

async function pythonExe() {
  // Prefer the project venv so the same deps/interpreter as the pipeline are used.
  const candidates = [
    path.join(SCRIPTS, ".venv", "Scripts", "python.exe"), // Windows
    path.join(SCRIPTS, ".venv", "bin", "python"), // *nix
  ];
  for (const c of candidates) if (await exists(c)) return c;
  return process.platform === "win32" ? "python" : "python3";
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);

    if (req.method === "GET" && url.pathname === "/") {
      return send(res, 200, await readFile(path.join(__dirname, "index.html")), "text/html; charset=utf-8");
    }

    if (req.method === "GET" && url.pathname === "/api/data") {
      const players = await readJson(path.join(DATA, "players.json"), { players: [] });
      const overrides = await readJson(path.join(DATA, "overrides.json"), { players: {}, added_players: [] });
      return send(res, 200, { players, overrides });
    }

    if (req.method === "POST" && url.pathname === "/api/overrides") {
      const raw = await readBody(req);
      let parsed;
      try {
        parsed = JSON.parse(raw); // validate before writing
      } catch (e) {
        return send(res, 400, { error: "Invalid JSON: " + e.message });
      }
      await writeFile(path.join(DATA, "overrides.json"), JSON.stringify(parsed, null, 2) + "\n", "utf8");
      return send(res, 200, { ok: true });
    }

    if (req.method === "POST" && url.pathname === "/api/rebuild") {
      const py = await pythonExe();
      const child = spawn(py, ["build_players.py"], { cwd: SCRIPTS });
      let out = "";
      child.stdout.on("data", (d) => (out += d));
      child.stderr.on("data", (d) => (out += d));
      child.on("close", (code) => send(res, code === 0 ? 200 : 500, { ok: code === 0, output: out.trim() }));
      return;
    }

    send(res, 404, { error: "not found" });
  } catch (e) {
    send(res, 500, { error: String(e) });
  }
});

server.listen(PORT, () => {
  console.log(`\n  BeyondCLTFC editor → http://localhost:${PORT}\n  Saves to ${path.join(DATA, "overrides.json")}\n  Ctrl+C to stop.\n`);
});
