# Job Alert Bot — Phase 1

Monitors 6 companies' career pages (DoorDash, HubSpot, Snap, Spotify, Clay, Coca-Cola) via their
ATS APIs every ~10 minutes, filters new postings against your profile using Claude, sends a
Telegram alert with a link for matches, and shows all matches on a password-protected dark-mode
dashboard with per-company on/off toggles.

**Cost estimate:** ~$3-6/month in Claude API calls. Hosting is free (GitHub Actions free tier +
Cloudflare Workers free tier).

---

## What's in this repo

```
poller/              Python script run by GitHub Actions on a schedule
  ats_fetchers.py       Pulls live postings from each ATS's JSON API
  keyword_filter.py     Free local pre-filter (title keyword match) before any AI call
  claude_judge.py        Calls Claude to judge fit for postings that pass the pre-filter
  telegram.py            Sends the Telegram alert
  run.py                  Orchestrates all of the above
.github/workflows/poll.yml   The schedule + on-demand resync trigger
dashboard/worker.js          Cloudflare Worker: password lock + dashboard + toggle API
dashboard/wrangler.toml      Worker config
state/state.json             Single source of truth: company config, toggles, seen jobs, matches
state/candidate_profile.md   Your condensed profile used in every fit-judgment call
```

---

## ⚠️ Before you deploy — 2 values need verifying

I could not independently confirm two companies' exact API identifiers from search alone.
Fix these in `state/state.json` before first run:

1. **Snap (SmartRecruiters):** `"board_token": "VERIFY_ME_Snap"` — find the correct company
   slug by opening SmartRecruiters' public postings API pattern
   (`https://api.smartrecruiters.com/v1/companies/{slug}/postings`) and testing slug candidates
   like `Snap`, `SnapInc`, or `Snapchat` in a browser until one returns real job data.
2. **Coca-Cola (Workday):** `"workday_tenant"` and `"workday_site"` are placeholders. Open
   Coca-Cola's careers site, let it redirect to the `*.wd1.myworkdayjobs.com` URL, and read the
   tenant (subdomain, likely `coke`) and site name (the path segment right after the domain,
   e.g. `/en-US/CocaColaCareers` → site = `CocaColaCareers`) directly from your browser's address
   bar.

Everything else (DoorDash, HubSpot, Spotify, Clay) is confirmed and ready to run as-is.

---

## Setup steps

### 1. Create the GitHub repo
Push this project to a **private** repo (it contains your candidate profile).

### 2. Create a Telegram bot
1. Message `@BotFather` on Telegram → `/newbot` → follow prompts → copy the **bot token**.
2. Message your new bot once (anything).
3. Visit `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser, find `"chat":{"id": ...}` → copy your **chat ID**.

### 3. Get an Anthropic API key
From console.anthropic.com → copy your key.

### 4. Add GitHub Actions secrets
In your repo: Settings → Secrets and variables → Actions → New repository secret. Add:
- `ANTHROPIC_API_KEY`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

### 5. Do a manual first run
Actions tab → "Poll job boards" → Run workflow (leave the company field blank). This does the
initial full sync for all 6 companies. Check that `state/state.json` gets updated with job IDs
and that no errors appear in the log — especially for Snap/Coca-Cola until you've verified their
identifiers per the warning above.

### 6. Create a GitHub Personal Access Token for the dashboard
GitHub → Settings → Developer settings → Fine-grained tokens → New token, scoped to just this
repo, with **Contents: Read and write** and **Actions: Read and write** permissions.

### 7. Deploy the Cloudflare Worker
1. Install wrangler: `npm install -g wrangler`
2. `cd dashboard && wrangler login`
3. Set secrets:
   ```
   wrangler secret put DASHBOARD_PASSWORD
   wrangler secret put GITHUB_TOKEN        # the PAT from step 6
   wrangler secret put GITHUB_OWNER        # your GitHub username
   wrangler secret put GITHUB_REPO         # e.g. job-bot
   wrangler secret put GITHUB_BRANCH       # main
   ```
4. `wrangler deploy`
5. Visit the URL wrangler gives you, log in with your password.

---

## How it behaves

- **Every ~10 min:** GitHub Actions checks all *enabled* companies for new postings, runs the
  free keyword filter, sends anything that survives to Claude for judgment, and Telegrams you
  any match with a direct link.
- **Toggle a company off:** it's immediately excluded from future polls (saving cost) and its
  roles disappear from the "Open Roles" tab — but the underlying data isn't deleted, so nothing
  is lost.
- **Toggle a company back on:** the dashboard instantly writes the change to GitHub *and* fires
  an immediate workflow run scoped to just that company, which re-evaluates every currently-live
  posting there (a full catch-up, no Telegram spam for the backlog) before falling back to the
  normal 10-minute schedule.

## Extending later (Phase 2)

To add one of the harder custom-platform companies later, you'd add a new fetcher function to
`ats_fetchers.py` (following the same normalized-dict pattern) and a new entry in
`state/state.json`. Everything else — the filter, the Claude judgment, the dashboard, the
toggles — works unchanged.
