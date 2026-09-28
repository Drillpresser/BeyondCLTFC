// Local editor server for BeyondCLTFC — zero dependencies (Node built-ins only).
//
// A standalone, local-only tool: it's intentionally separate from the site in
// web/ (its own package.json, not in the deploy workflow) so it never ships to
// GitHub Pages. Serves the wizard UI and a tiny API to read the dataset and
// write manual edits to data/overrides.json.
//
//   cd editor && npm start          (or: node editor/server.mjs  from repo root)
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
  // Strings and Buffers (e.g. the index.html file read) go out as-is; anything
  // else (API objects) is JSON-encoded.
  res.end(typeof body === "string" || Buffer.isBuffer(body) ? body : JSON.stringify(body));
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

// --- Publish mode (EDITOR_PUBLISH=1, used on the home server) -----------------
// Saving commits data/overrides.json + the rebuilt players.json to master and
// pushes, so the site redeploys and the weekly refresh (which resets its own
// clone to origin/master) keeps the edit. This clone belongs to the editor:
// it is hard-reset to origin/master before every read and write.
const PUBLISH = process.env.EDITOR_PUBLISH === "1";
const BRANCH = process.env.EDITOR_BRANCH || "master";

function run(cmd, args, cwd = ROOT) {
  return new Promise((resolve) => {
    const child = spawn(cmd, args, { cwd });
    let out = "";
    child.stdout.on("data", (d) => (out += d));
    child.stderr.on("data", (d) => (out += d));
    child.on("error", (e) => resolve({ code: -1, out: String(e) }));
    child.on("close", (code) => resolve({ code, out: out.trim() }));
  });
}

async function git(...args) {
  const r = await run("git", args);
  if (r.code !== 0) throw new Error(`git ${args[0]} failed:\n${r.out}`);
  return r.out;
}

async function syncToRemote() {
  await git("fetch", "--quiet", "origin", BRANCH);
  await git("reset", "--quiet", "--hard", `origin/${BRANCH}`);
}

async function rebuild() {
  const r = await run(await pythonExe(), ["build_players.py"], SCRIPTS);
  return { ok: r.code === 0, output: r.out };
}

// One git operation at a time: two saves racing would clobber each other.
let queue = Promise.resolve();
function serialized(fn) {
  const p = queue.then(fn);
  queue = p.catch(() => {});
  return p;
}

async function publish(overrides, message) {
  for (let attempt = 1; attempt <= 3; attempt++) {
    await syncToRemote();
    await writeFile(path.join(DATA, "overrides.json"), JSON.stringify(overrides, null, 2) + "\n", "utf8");
    const b = await rebuild();
    if (!b.ok) throw new Error("build_players.py failed:\n" + b.output);
    await git("add", "data/overrides.json", "data/players.json");
    if ((await run("git", ["diff", "--cached", "--quiet"])).code === 0) {
      return { ok: true, commit: null, note: "No changes to publish." };
    }
    await git("-c", "user.name=beyondcltfc-editor", "-c", "user.email=beyondcltfc-bot@users.noreply.github.com",
      "commit", "--quiet", "-m", message);
    const push = await run("git", ["push", "--quiet", "origin", `HEAD:${BRANCH}`]);
    if (push.code === 0) return { ok: true, commit: await git("rev-parse", "--short", "HEAD") };
    // The weekly refresh pushed in between: start over from the new master.
    if (!/rejected|fetch first|non-fast-forward/i.test(push.out)) throw new Error("git push failed:\n" + push.out);
  }
  throw new Error("git push was rejected 3 times; try again in a minute.");
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://localhost:${PORT}`);

    if (req.method === "GET" && url.pathname === "/") {
      return send(res, 200, await readFile(path.join(__dirname, "index.html")), "text/html; charset=utf-8");
    }

    if (req.method === "GET" && url.pathname === "/api/data") {
      if (PUBLISH) {
        // Show what's on GitHub now; if GitHub is unreachable, serve the last copy.
        await serialized(syncToRemote).catch((e) => console.error(String(e)));
      }
      const players = await readJson(path.join(DATA, "players.json"), { players: [] });
      const overrides = await readJson(path.join(DATA, "overrides.json"), { players: {}, added_players: [] });
      return send(res, 200, { players, overrides, publish: PUBLISH });
    }

    if (req.method === "POST" && url.pathname === "/api/overrides") {
      const raw = await readBody(req);
      let parsed;
      try {
        parsed = JSON.parse(raw); // validate before writing
      } catch (e) {
        return send(res, 400, { error: "Invalid JSON: " + e.message });
      }
      // Body is {overrides, message}; a bare overrides object is still accepted.
      const overrides = parsed && parsed.overrides ? parsed.overrides : parsed;
      if (!overrides || typeof overrides.players !== "object") {
        return send(res, 400, { error: "Expected an overrides object with a `players` map." });
      }
      if (PUBLISH) {
        const message = String(parsed.message || "data: manual edit").slice(0, 200);
        try {
          return send(res, 200, await serialized(() => publish(overrides, message)));
        } catch (e) {
          return send(res, 500, { error: String(e.message || e) });
        }
      }
      await writeFile(path.join(DATA, "overrides.json"), JSON.stringify(overrides, null, 2) + "\n", "utf8");
      return send(res, 200, { ok: true });
    }

    if (req.method === "POST" && url.pathname === "/api/rebuild") {
      const r = await rebuild();
      return send(res, r.ok ? 200 : 500, r);
    }

    send(res, 404, { error: "not found" });
  } catch (e) {
    send(res, 500, { error: String(e) });
  }
});

server.listen(PORT, () => {
  const mode = PUBLISH ? `Publish mode: saves are committed and pushed to ${BRANCH}` : `Saves to ${path.join(DATA, "overrides.json")}`;
  console.log(`\n  BeyondCLTFC editor → http://localhost:${PORT}\n  ${mode}\n  Ctrl+C to stop.\n`);
});
