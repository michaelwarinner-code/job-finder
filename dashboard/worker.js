/**
 * Cloudflare Worker: password-protected dashboard for the job alert bot.
 *
 * Required environment variables / secrets (set via `wrangler secret put` or
 * the Cloudflare dashboard):
 *   DASHBOARD_PASSWORD   - the password you type in to view the dashboard
 *   GITHUB_TOKEN         - a fine-grained GitHub PAT with contents:write and
 *                          actions:write on this one repo
 *   GITHUB_OWNER         - your GitHub username
 *   GITHUB_REPO          - the repo name (e.g. "job-bot")
 *   GITHUB_BRANCH        - usually "main"
 */

const COOKIE_NAME = "job_bot_session";

function toBase64(str) {
  const bytes = new TextEncoder().encode(str);
  let binary = "";
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i]);
  return btoa(binary);
}

function fromBase64(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new TextDecoder().decode(bytes);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/login" && request.method === "POST") {
      return handleLogin(request, env);
    }

    if (!isAuthed(request, env)) {
      return htmlResponse(loginPage());
    }

    if (url.pathname === "/api/state" && request.method === "GET") {
      return handleGetState(env);
    }

    if (url.pathname === "/api/toggle" && request.method === "POST") {
      return handleToggle(request, env);
    }

    if (url.pathname === "/" || url.pathname === "") {
      return htmlResponse(dashboardPage());
    }

    return new Response("Not found", { status: 404 });
  },
};

// ---------- Auth ----------

function isAuthed(request, env) {
  const cookie = request.headers.get("Cookie") || "";
  const match = cookie.match(new RegExp(`${COOKIE_NAME}=([^;]+)`));
  return match && match[1] === env.DASHBOARD_PASSWORD;
}

async function handleLogin(request, env) {
  const form = await request.formData();
  const password = form.get("password");
  if (password !== env.DASHBOARD_PASSWORD) {
    return htmlResponse(loginPage("Incorrect password."));
  }
  const headers = new Headers({ Location: "/" });
  headers.append(
    "Set-Cookie",
    `${COOKIE_NAME}=${password}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000`
  );
  return new Response(null, { status: 302, headers });
}

// ---------- GitHub helpers ----------

const GH_API = "https://api.github.com";

function ghHeaders(env) {
  return {
    Authorization: `Bearer ${env.GITHUB_TOKEN}`,
    Accept: "application/vnd.github+json",
    "User-Agent": "job-bot-dashboard",
  };
}

async function getStateFile(env) {
  const path = "state/state.json";
  const res = await fetch(
    `${GH_API}/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/contents/${path}?ref=${env.GITHUB_BRANCH}`,
    { headers: ghHeaders(env) }
  );
  if (!res.ok) throw new Error(`GitHub read failed: ${res.status}`);
  const data = await res.json();
  const content = fromBase64(data.content.replace(/\n/g, ""));
  return { json: JSON.parse(content), sha: data.sha };
}

async function putStateFile(env, newJson, sha, message) {
  const path = "state/state.json";
  const body = {
    message,
    content: toBase64(JSON.stringify(newJson, null, 2)),
    sha,
    branch: env.GITHUB_BRANCH,
  };
  const res = await fetch(
    `${GH_API}/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/contents/${path}`,
    { method: "PUT", headers: { ...ghHeaders(env), "Content-Type": "application/json" }, body: JSON.stringify(body) }
  );
  if (!res.ok) throw new Error(`GitHub write failed: ${res.status} ${await res.text()}`);
}

async function triggerResync(env, companyKey) {
  const res = await fetch(
    `${GH_API}/repos/${env.GITHUB_OWNER}/${env.GITHUB_REPO}/actions/workflows/poll.yml/dispatches`,
    {
      method: "POST",
      headers: { ...ghHeaders(env), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: env.GITHUB_BRANCH, inputs: { company: companyKey } }),
    }
  );
  if (!res.ok) console.log(`workflow_dispatch failed: ${res.status} ${await res.text()}`);
}

// ---------- API handlers ----------

async function handleGetState(env) {
  try {
    const { json } = await getStateFile(env);
    return jsonResponse(json);
  } catch (e) {
    return jsonResponse({ error: String(e) }, 500);
  }
}

async function handleToggle(request, env) {
  const { company_key, enabled } = await request.json();
  try {
    const { json, sha } = await getStateFile(env);
    if (!json.companies[company_key]) {
      return jsonResponse({ error: "unknown company" }, 400);
    }
    json.companies[company_key].enabled = enabled;
    if (enabled) {
      json.companies[company_key].needs_resync = true;
    }
    await putStateFile(env, json, sha, `Toggle ${company_key} -> ${enabled}`);
    if (enabled) {
      await triggerResync(env, company_key);
    }
    return jsonResponse({ ok: true });
  } catch (e) {
    return jsonResponse({ error: String(e) }, 500);
  }
}

// ---------- Responses ----------

function htmlResponse(html) {
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}
function jsonResponse(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json" } });
}

// ---------- Pages ----------

function loginPage(error = "") {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Alerts</title>
<style>
  body{background:#0b0b0f;color:#f2f2f2;font-family:-apple-system,Segoe UI,Roboto,sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
  form{background:#17171d;padding:2.5rem;border-radius:16px;width:280px;box-shadow:0 8px 30px rgba(0,0,0,.5)}
  h1{font-size:1.1rem;margin:0 0 1.5rem;font-weight:700;letter-spacing:-.02em}
  input{width:100%;padding:.8rem;border-radius:10px;border:1px solid #2a2a33;background:#0e0e13;color:#fff;
        font-size:1rem;box-sizing:border-box;margin-bottom:1rem}
  button{width:100%;padding:.8rem;border-radius:10px;border:none;background:#5b6cff;color:#fff;
         font-weight:700;font-size:1rem;cursor:pointer}
  .err{color:#ff6b6b;font-size:.85rem;margin-bottom:1rem}
</style></head><body>
<form method="POST" action="/login">
  <h1>Job Alerts Dashboard</h1>
  ${error ? `<div class="err">${error}</div>` : ""}
  <input type="password" name="password" placeholder="Password" autofocus>
  <button type="submit">Enter</button>
</form>
</body></html>`;
}

function dashboardPage() {
  return `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Alerts</title>
<style>
  :root{--bg:#0b0b0f;--card:#17171d;--card2:#1e1e26;--border:#2a2a33;--accent:#5b6cff;--text:#f2f2f2;--muted:#8a8a96}
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--text);font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;padding:1.5rem}
  h1{font-size:1.3rem;font-weight:800;letter-spacing:-.02em;margin:0 0 1.2rem}
  .tabs{display:flex;gap:.5rem;margin-bottom:1.2rem}
  .tab{padding:.6rem 1.1rem;border-radius:999px;background:var(--card);color:var(--muted);
       font-weight:700;font-size:.9rem;cursor:pointer;border:1px solid var(--border)}
  .tab.active{background:var(--accent);color:#fff;border-color:var(--accent)}
  .company-group{margin-bottom:1.4rem}
  .company-name{font-size:.8rem;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);
                font-weight:700;margin:0 0 .5rem}
  .role{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:.9rem 1rem;
        margin-bottom:.5rem;display:block;text-decoration:none;color:var(--text)}
  .role:hover{background:var(--card2)}
  .role-title{font-weight:700;font-size:.95rem}
  .role-meta{color:var(--muted);font-size:.8rem;margin-top:.25rem}
  .role-reason{color:var(--muted);font-size:.78rem;margin-top:.4rem;font-style:italic}
  .company-row{display:flex;align-items:center;justify-content:space-between;background:var(--card);
               border:1px solid var(--border);border-radius:12px;padding:.9rem 1rem;margin-bottom:.5rem}
  .switch{position:relative;width:46px;height:26px}
  .switch input{opacity:0;width:0;height:0}
  .slider{position:absolute;cursor:pointer;inset:0;background:#33333c;border-radius:999px;transition:.15s}
  .slider:before{content:"";position:absolute;height:20px;width:20px;left:3px;top:3px;background:#fff;
                 border-radius:50%;transition:.15s}
  input:checked + .slider{background:var(--accent)}
  input:checked + .slider:before{transform:translateX(20px)}
  .empty{color:var(--muted);text-align:center;padding:2rem 0;font-size:.9rem}
</style></head><body>
<h1>Job Alerts</h1>
<div class="tabs">
  <div class="tab active" id="tab-roles-btn" onclick="showTab('roles')">Open Roles</div>
  <div class="tab" id="tab-companies-btn" onclick="showTab('companies')">Companies</div>
</div>
<div id="tab-roles"></div>
<div id="tab-companies" style="display:none"></div>

<script>
let state = null;

async function load() {
  const res = await fetch('/api/state');
  state = await res.json();
  renderRoles();
  renderCompanies();
}

function renderRoles() {
  const container = document.getElementById('tab-roles');
  const enabledKeys = new Set(Object.keys(state.companies).filter(k => state.companies[k].enabled));
  const matches = (state.matches || []).filter(m => enabledKeys.has(m.company_key));

  if (matches.length === 0) {
    container.innerHTML = '<div class="empty">No matching roles yet. Check back soon.</div>';
    return;
  }

  const byCompany = {};
  for (const m of matches) {
    (byCompany[m.company_name] ||= []).push(m);
  }
  const companyNames = Object.keys(byCompany).sort((a,b) => a.localeCompare(b));

  container.innerHTML = companyNames.map(name => \`
    <div class="company-group">
      <div class="company-name">\${name}</div>
      \${byCompany[name].map(m => \`
        <a class="role" href="\${m.url}" target="_blank">
          <div class="role-title">\${m.title}</div>
          <div class="role-meta">\${m.location || ''}</div>
          <div class="role-reason">\${m.fit_reason || ''}</div>
        </a>
      \`).join('')}
    </div>
  \`).join('');
}

function renderCompanies() {
  const container = document.getElementById('tab-companies');
  const keys = Object.keys(state.companies).sort((a,b) =>
    state.companies[a].name.localeCompare(state.companies[b].name));

  container.innerHTML = keys.map(key => {
    const c = state.companies[key];
    return \`
      <div class="company-row">
        <div>\${c.name}</div>
        <label class="switch">
          <input type="checkbox" \${c.enabled ? 'checked' : ''} onchange="toggle('\${key}', this.checked)">
          <span class="slider"></span>
        </label>
      </div>
    \`;
  }).join('');
}

async function toggle(companyKey, enabled) {
  await fetch('/api/toggle', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({company_key: companyKey, enabled})
  });
  await load();
}

function showTab(name) {
  document.getElementById('tab-roles').style.display = name === 'roles' ? 'block' : 'none';
  document.getElementById('tab-companies').style.display = name === 'companies' ? 'block' : 'none';
  document.getElementById('tab-roles-btn').classList.toggle('active', name === 'roles');
  document.getElementById('tab-companies-btn').classList.toggle('active', name === 'companies');
}

load();
setInterval(load, 30000);
</script>
</body></html>`;
}
