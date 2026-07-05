"""
LiveRepo full-stack demo -- backend + frontend in ONE deployable container.

This is a tiny "message wall": visitors leave a message, it's POSTed to the
Flask API, stored in SQLite, and every browser polling the API sees it appear.
It exists to prove a single point about LiveRepo: you can push a repo that has
a real backend AND a real frontend that talk to each other, and get one live URL.

Why it's built the way it is (all three matter because of how LiveRepo serves it):

  * ONE process serves BOTH tiers. LiveRepo runs one container and publishes one
    port, so the Flask app serves the HTML page at "/" and the JSON API under
    "/api/...". Same origin, no CORS, nothing else to deploy.

  * The frontend computes its API base from window.location at RUNTIME. LiveRepo
    serves this under "/proxy/<user>/<repo>/" and its reverse proxy strips that
    prefix without rewriting the HTML. So the page can't hardcode "/api/state"
    (that would drop the prefix and hit the wrong server) -- it derives the base
    from wherever it happens to be loaded. That makes it work identically at
    localhost:8000 and behind the proxy.

  * State lives in SQLite on disk, not in memory. LiveRepo sleeps idle containers
    with `docker stop` and wakes them with `docker start`, which keeps the
    container's filesystem. So messages written before a nap are still there after
    it -- while the in-memory request counter resets, which nicely visualizes that
    the *process* restarted but the *data* survived.
"""

from __future__ import annotations

import os
import platform
import socket
import sqlite3
import time
from datetime import datetime, timezone

from flask import Flask, g, jsonify, request

app = Flask(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guestbook.db")

# Process-scoped facts. STARTED_AT and REQUEST_COUNT reset every time the
# container (re)starts -- that's intentional, it's how you can see a cold start.
STARTED_AT = time.time()
REQUEST_COUNT = 0


def db() -> sqlite3.Connection:
    """One connection per request, stored on Flask's `g`."""
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def _close_db(_exc: object) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db() -> None:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT NOT NULL,
            text       TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    # Seed one welcome message the first time the DB is created, so a fresh
    # deploy never shows a bare empty wall.
    count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    if count == 0:
        conn.execute(
            "INSERT INTO messages (name, text, created_at) VALUES (?, ?, ?)",
            ("LiveRepo", "This message came from a Flask backend + SQLite, "
                         "running in the same container that served this page. "
                         "Add your own below ⬇️", _now_iso()),
        )
    conn.commit()
    conn.close()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _server_info() -> dict:
    """The 'proof a real backend is alive' panel."""
    return {
        "hostname": socket.gethostname(),          # Docker gives each container a unique short id
        "python": platform.python_version(),
        "started_at": datetime.fromtimestamp(STARTED_AT, timezone.utc).isoformat(timespec="seconds"),
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "request_count": REQUEST_COUNT,             # resets on restart -> visualizes cold starts
        "message_count": db().execute("SELECT COUNT(*) FROM messages").fetchone()[0],
        "now": _now_iso(),
    }


def _messages() -> list[dict]:
    rows = db().execute(
        "SELECT id, name, text, created_at FROM messages ORDER BY id DESC LIMIT 100"
    ).fetchall()
    return [dict(r) for r in rows]


@app.before_request
def _count_requests() -> None:
    global REQUEST_COUNT
    REQUEST_COUNT += 1


@app.get("/api/state")
def api_state():
    """Everything the frontend needs in one round trip: server stats + messages."""
    return jsonify(server=_server_info(), messages=_messages())


@app.post("/api/messages")
def api_add_message():
    """Frontend -> backend write. Validates, stores in SQLite, returns fresh state."""
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name", "")).strip()[:40]
    text = str(payload.get("text", "")).strip()[:280]
    if not name or not text:
        return jsonify(error="Both a name and a message are required."), 400

    conn = db()
    conn.execute(
        "INSERT INTO messages (name, text, created_at) VALUES (?, ?, ?)",
        (name, text, _now_iso()),
    )
    conn.commit()
    return jsonify(server=_server_info(), messages=_messages()), 201


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.get("/")
def index():
    # Served as one self-contained page: inline CSS + JS, zero external assets,
    # so there's nothing whose URL the reverse proxy could break.
    return app.response_class(INDEX_HTML, mimetype="text/html")


# --------------------------------------------------------------------------- #
# The frontend. One file, inline everything. The only "clever" bit is API_BASE:
# it's derived from window.location so the exact same HTML works at
# http://localhost:8000/ and behind LiveRepo's /proxy/<user>/<repo>/ prefix.
# --------------------------------------------------------------------------- #
INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>LiveRepo Full-Stack Demo</title>
<style>
  :root {
    --bg: #0b1020; --panel: #141b31; --panel-2: #1b2440; --line: #263252;
    --ink: #e8ecf7; --muted: #93a0c0; --accent: #6ea8fe; --accent-2: #59e6b8;
    --danger: #ff6b7d; --radius: 14px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; min-height: 100vh; color: var(--ink);
    font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    background:
      radial-gradient(1200px 600px at 80% -10%, #1c2b52 0%, transparent 55%),
      radial-gradient(900px 500px at -10% 10%, #143f39 0%, transparent 50%),
      var(--bg);
  }
  .wrap { max-width: 860px; margin: 0 auto; padding: 32px 20px 64px; }
  header h1 { margin: 0 0 6px; font-size: 26px; letter-spacing: -0.02em; }
  header p { margin: 0; color: var(--muted); }
  .badge {
    display: inline-block; margin-bottom: 18px; padding: 4px 10px; border-radius: 999px;
    background: rgba(110,168,254,.12); color: var(--accent);
    border: 1px solid rgba(110,168,254,.35); font-size: 12px; font-weight: 600;
  }
  .grid { display: grid; grid-template-columns: 1fr; gap: 18px; margin-top: 22px; }
  @media (min-width: 720px) { .grid { grid-template-columns: 1.1fr 1fr; align-items: start; } }
  .card {
    background: linear-gradient(180deg, var(--panel), var(--panel-2));
    border: 1px solid var(--line); border-radius: var(--radius); padding: 18px 18px;
  }
  .card h2 { margin: 0 0 14px; font-size: 14px; text-transform: uppercase;
             letter-spacing: .08em; color: var(--muted); }
  .stat { display: flex; justify-content: space-between; gap: 12px; padding: 7px 0;
          border-bottom: 1px dashed var(--line); }
  .stat:last-child { border-bottom: 0; }
  .stat .k { color: var(--muted); }
  .stat .v { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: var(--accent-2); }
  .pulse { width: 8px; height: 8px; border-radius: 50%; background: var(--accent-2);
           display: inline-block; margin-right: 7px; box-shadow: 0 0 0 0 rgba(89,230,184,.7);
           animation: pulse 1.8s infinite; }
  @keyframes pulse { 0% { box-shadow: 0 0 0 0 rgba(89,230,184,.6); }
                     70% { box-shadow: 0 0 0 9px rgba(89,230,184,0); }
                     100% { box-shadow: 0 0 0 0 rgba(89,230,184,0); } }
  form { display: grid; gap: 10px; }
  input, textarea, button { font: inherit; }
  input, textarea {
    width: 100%; padding: 10px 12px; color: var(--ink);
    background: #0e152b; border: 1px solid var(--line); border-radius: 10px; resize: vertical;
  }
  input:focus, textarea:focus { outline: 2px solid rgba(110,168,254,.5); border-color: transparent; }
  button {
    padding: 11px 14px; border: 0; border-radius: 10px; cursor: pointer; font-weight: 700;
    color: #05131f; background: linear-gradient(180deg, var(--accent), #4f8ff7);
  }
  button:disabled { opacity: .6; cursor: default; }
  .err { color: var(--danger); font-size: 13px; min-height: 18px; margin: 2px 0 0; }
  ul.msgs { list-style: none; margin: 16px 0 0; padding: 0; display: grid; gap: 10px; }
  ul.msgs li { background: #0e152b; border: 1px solid var(--line); border-radius: 10px; padding: 10px 12px; }
  ul.msgs .who { font-weight: 700; }
  ul.msgs .when { color: var(--muted); font-size: 12px; }
  ul.msgs .body { margin-top: 3px; white-space: pre-wrap; word-break: break-word; }
  .foot { margin-top: 26px; color: var(--muted); font-size: 12.5px; text-align: center; }
  code { font-family: ui-monospace, Menlo, monospace; color: var(--accent); }
</style>
</head>
<body>
  <div class="wrap">
    <header>
      <span class="badge">▲ Deployed with LiveRepo</span>
      <h1>Full-Stack Demo — one repo, one link</h1>
      <p>This page (frontend) and the API it talks to (backend + SQLite) are the
         <strong>same container</strong>, deployed from a single repo.</p>
    </header>

    <div class="grid">
      <section class="card">
        <h2><span class="pulse"></span>Live backend status</h2>
        <div id="server">
          <div class="stat"><span class="k">Connecting to backend…</span><span class="v">…</span></div>
        </div>
      </section>

      <section class="card">
        <h2>Leave a message</h2>
        <form id="form">
          <input id="name" placeholder="Your name" maxlength="40" autocomplete="off" />
          <textarea id="text" placeholder="Say something — it gets POSTed to the backend and stored in SQLite" rows="3" maxlength="280"></textarea>
          <button id="send" type="submit">Post to backend →</button>
          <p class="err" id="err"></p>
        </form>
      </section>
    </div>

    <section class="card" style="margin-top:18px">
      <h2>Message wall <span id="count" class="when"></span></h2>
      <ul class="msgs" id="msgs"><li>Loading messages from the backend…</li></ul>
    </section>

    <p class="foot">
      Frontend ⇄ Backend over <code id="apibase">…</code> ·
      leave it idle ~15 min and LiveRepo puts the container to sleep — your
      messages persist (SQLite on disk), the request counter resets (fresh process).
    </p>
  </div>

<script>
  // Works at localhost:8000/ AND behind LiveRepo's /proxy/<user>/<repo>/ prefix:
  // derive the base from where THIS page was loaded, strip any trailing slash.
  var API_BASE = window.location.pathname.replace(/\/+$/, "");
  document.getElementById("apibase").textContent = (API_BASE || "/") + "/api";

  var FETCH_OPTS = { headers: { "ngrok-skip-browser-warning": "true" } };

  function esc(s) { var d = document.createElement("div"); d.textContent = s; return d.innerHTML; }

  function renderServer(s) {
    var rows = [
      ["container host", s.hostname],
      ["python", s.python],
      ["uptime", s.uptime_seconds + "s"],
      ["requests since start", s.request_count],
      ["messages stored", s.message_count],
      ["server time (UTC)", s.now.replace("T", " ").replace("+00:00", "")],
    ];
    document.getElementById("server").innerHTML = rows.map(function (r) {
      return '<div class="stat"><span class="k">' + esc(r[0]) +
             '</span><span class="v">' + esc(String(r[1])) + "</span></div>";
    }).join("");
  }

  function renderMessages(msgs) {
    document.getElementById("count").textContent = "(" + msgs.length + ")";
    if (!msgs.length) { document.getElementById("msgs").innerHTML = "<li>No messages yet — be the first!</li>"; return; }
    document.getElementById("msgs").innerHTML = msgs.map(function (m) {
      var when = (m.created_at || "").replace("T", " ").replace("+00:00", "");
      return "<li><span class='who'>" + esc(m.name) + "</span> " +
             "<span class='when'>" + esc(when) + " UTC</span>" +
             "<div class='body'>" + esc(m.text) + "</div></li>";
    }).join("");
  }

  function refresh() {
    return fetch(API_BASE + "/api/state", FETCH_OPTS)
      .then(function (r) { return r.json(); })
      .then(function (d) { renderServer(d.server); renderMessages(d.messages); })
      .catch(function () {/* transient during a cold start; next poll recovers */});
  }

  document.getElementById("form").addEventListener("submit", function (e) {
    e.preventDefault();
    var name = document.getElementById("name").value.trim();
    var text = document.getElementById("text").value.trim();
    var errEl = document.getElementById("err");
    var btn = document.getElementById("send");
    errEl.textContent = "";
    if (!name || !text) { errEl.textContent = "Please fill in both fields."; return; }
    btn.disabled = true; btn.textContent = "Posting…";
    fetch(API_BASE + "/api/messages", {
      method: "POST",
      headers: { "Content-Type": "application/json", "ngrok-skip-browser-warning": "true" },
      body: JSON.stringify({ name: name, text: text }),
    })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) { errEl.textContent = res.d.error || "Something went wrong."; return; }
        document.getElementById("text").value = "";
        renderServer(res.d.server); renderMessages(res.d.messages);
      })
      .catch(function () { errEl.textContent = "Could not reach the backend."; })
      .finally(function () { btn.disabled = false; btn.textContent = "Post to backend →"; });
  });

  refresh();
  setInterval(refresh, 3000);   // keep the live-status panel and wall current
</script>
</body>
</html>
"""


if __name__ == "__main__":
    init_db()
    # 0.0.0.0 so the container's published port is reachable; 8000 matches EXPOSE.
    app.run(host="0.0.0.0", port=8000)
