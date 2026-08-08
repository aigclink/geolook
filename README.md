<div align="center">

# Geo**Look**

**Open-source, self-hosted platform for end-to-end GEO implementation**

For a specific project: status analysis → diagnosis → strategy → implementation tickets → execution → verification

English · [简体中文](README.zh-CN.md) · [日本語](README.ja.md)

![License](https://img.shields.io/badge/license-MIT-9184d9) ![Python](https://img.shields.io/badge/python-3.9%2B-9184d9) ![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Linux-9184d9) ![Deps](https://img.shields.io/badge/deps-requests%20·%20bs4%20·%20lxml-9184d9)

![Product demo](docs/demo.en.gif)

🌐 [Website geolook.cc](https://geolook.cc) · 🔍 [Live demo (read-only)](https://geolook.cc/demo/) · 📹 [HD demo video (mp4)](docs/demo.en.mp4) · 🖼 [All screenshots](docs/screenshots-en/)

<sub>Mirror while DNS propagates: [geolook.cc](https://geolook.cc) · [demo](https://geolook.cc/demo/)</sub>

</div>

> GEO = Generative Engine Optimization: getting AI engines (ChatGPT, Perplexity, Gemini, DeepSeek, Doubao…) to **proactively mention and cite your brand** when answering user questions. Not geographic info, not classic SEO.

## 1. Problems it solves

More and more users ask AI directly — "best tools for X", "X vs Y, which one". If your brand:

| Problem | What GeoLook gives you |
|---|---|
| **AI never mentions you** — you're not in the candidate set for category questions | Samples real answers engine by engine; quantifies mention rate / rank / citation share; diagnoses "absent" vs "competitor-dominated" |
| **You don't know why** — AI is a black box | 6-dimension site audit + gap diagnosis: uncrawlable pages? missing extraction blocks? absent from the channels AI actually cites? inconsistent messaging? |
| **Advice never lands** — recommendations pile up, nobody executes or verifies | Generates implementation tickets with acceptance criteria; 86% auto-verifiable in the sample project (18/21) — "done" is measured, not claimed |
| **Did the work even help?** | Per-question before/after across sampling rounds + task-level before/after |
| **You deliver GEO as a service and packaging is painful** | One click produces diagnosis report, strategy, execution plan, ticket CSV, and acceptance sheet for clients |

## 2. Feature map

Four stages plus operations, all in one self-hosted dashboard:

**Status** — Engine performance across 17 engines (10 automated via API + 7 manual, incl. Google AI Overviews and Metaso): mention rate, rank, citation share, what each engine actually cites, **sample replay** of raw answers, suspected-negative flags; **brand mention distribution** (you vs. competitors, per engine and aggregated); competitor tables with each rival's strongest engine one click away — plus each rival's **citation-source mix** and a "channels they have that you don't" hit-list; a 7-category question bank with **intent-group cards** (buyer / educate / probe — see at a glance which intent class you're absent from) where every question gets a **diagnosis type** (suspected-negative > competitor-dominated > absent > low-ranked); a **sample library** where every AI answer's metadata is browsable and human-correctable (regex parsing misreads — name collisions, negation — get fixed here; corrections recompute metrics instantly and survive re-sampling), with per-sample **citation-source breakdown** (domain × count · share) and sampling-environment provenance (sandbox / incognito / dedicated profile / personal — personal auto-downgrades to "needs review").

**Keyword mining** — expand the question bank from real search demand: Baidu suggest (CN) + Google autocomplete (Global) terms from brand/competitor/category roots (free public endpoints, no keys). Each round is snapshot-diffed to flag **rising demand** (affects topic ordering, never metrics); alternative/vs phrasings mined from competitor roots feed the Competitors page. Candidates only — adding to the bank is always a manual check.

![Engines](docs/screenshots-en/engines.png)
![Sample library](docs/screenshots-en/samples.png)

**Diagnosis** — Site audit organized as a **four-layer dependency chain** (Access → Orientation → Understanding → Quotability: each layer depends on the one above, and a failing Access layer makes everything downstream invisible to engines — the fix order is computed for you). The Access layer goes well beyond robots checks: RFC 9309-compliant robots parsing (catches wildcard-group blocks, shared UA groups and specificity overrides that line-by-line regexes miss), **WAF/CDN differential probing with real AI-crawler UAs** (robots may allow GPTBot while your CDN 403s it — invisible from a browser), X-Robots-Tag header noindex, llms.txt link validation, hreflang coverage, sitemap index-pollution and duplicate title/content detection. **Passage-level quotability**: retrieval picks passages, not pages — pages with sections but zero independently quotable passages get flagged with a concrete fix. Plus gap diagnosis (content → channels → facts); a **channel map of 19 channels** weighted by real citation-corpus data; and a **brand facts library** as the single source of truth that llms.txt, JSON-LD and content drafts are generated from.

![Site audit · four-layer chain](docs/screenshots-en/siteaudit.png)
![Channel map](docs/screenshots-en/channels.png)

**Action** — Structured tickets (rationale / owner / effort / window / acceptance criteria) carrying an independent **risk grade** (low-risk quick wins / observe with 7-14-28-day recheck / high-risk technical changes with backup & rollback discipline — priority says how important, risk says how careful), with "first-measured → current → target" progress bars and automatic reopening on regressions; tickets deep-link to the exact question they most need written; a **content workbench** (topic pool sorted by "not mentioned + no content", required extraction blocks and brand facts at hand, live citability pre-check, fabrication-risk lint for AI drafts, and a **distribution checklist** matching each piece to its target channels); **deploy assets** (llms.txt, JSON-LD, HTML snippets, plus an **AI-traffic attribution pack**: GA4 "AI engines" channel-group regex, server-log counting script, source-snapshot guidance — closing the loop from "cited" to "converts"); **publishing** with channels grouped General / China / Global — GitHub, WordPress drafts, WeChat OA drafts, webhook, plus real **X** (teaser tweet with auto-backlink to your latest long-form publish) and **Reddit** (full-markdown self-post) integrations, each with an in-dialog step-by-step credential guide; multi-channel checkbox publishing per article, and publish status synced back to the action plan, pending list and question bank. Platforms without a personally usable official API (Weibo, Xiaohongshu, Toutiao, Bilibili, LinkedIn, Facebook, Instagram) are deliberately **not** integrated — better absent than fake; the page says why and offers the webhook bridge instead. Publishing is always manually confirmed, article by article.

![Action plan](docs/screenshots-en/plan.png)
![Workbench](docs/screenshots-en/workbench.png)
![Publishing channels](docs/screenshots-en/publishing.png)

**Results** — Per-question before/after (all / CN / global tabs), task-level before/after, verification history; boss-ready one-pager, execution plan, and a complete client delivery package (HTML + CSV).

**Operations** — Scheduled full-cycle re-runs (every 7/14/30 days; register the dashboard as a **macOS standing service** with `scripts/service.sh install` — starts at login, restarts on crash, keeps running with every terminal closed, so scheduled re-runs actually fire), multi-brand with one-click switching, and a manual-sampling loop that feeds the same metrics: export a full sheet or a **weekly buyer-intent sheet** (`sample-sheet --intent buyer --limit 20`), or use the **Chrome sampling assistant** below.

**Sampling assistant (Chrome extension, `extension/`)** — for the engines without APIs, which is where the real users are. Side panel loads your buyer-intent queue (grouped by intent), fills the question into the chat box (**you** press Enter in the default manual mode), extracts the finished answer with all citation links in one click, and posts samples back to your local dashboard as A-grade evidence — a weekly check drops from ~30 minutes to ~10. An explicit opt-in auto-run mode exists with hard guardrails (you stay present, rate-limited, capped, halts on any CAPTCHA/anti-bot signal — ToS risks documented honestly in its README). Ships with `sandbox.sh`: one command launches a disposable clean-browser sandbox (no history, no cookies, extension auto-loaded) or a persistent logged-in profile for engines that require accounts, so sampling hygiene ("what a stranger sees, not what AI thinks of you") is one command instead of a discipline.

## 3. How it differs from other GEO tools

Most GEO products are **monitoring SaaS**: they show mention rates and rankings, charge monthly, and keep your data in their cloud. GeoLook is an **implementation platform**:

| | Typical GEO monitoring SaaS | GeoLook |
|---|---|---|
| **Loop depth** | Monitor + advise | Monitor → diagnose → **tickets → assets → auto-verify → deliver** |
| **Verification** | None (or manual check-off) | Programmatic: re-crawl + next sampling round decide; regressions reopen automatically |
| **Metrics** | Black-box scores | Fully reproducible; a "where do these numbers come from" panel in the UI; unmeasured shows "unmeasured", never faked |
| **Chinese market** | Mostly Western engines | First-class CN engine matrix (GLM / Doubao / DeepSeek / Kimi / MiniMax / Nano / Baidu AI) + CN channels calibrated on citation-corpus data (Baike, ranking sites, WeChat, Toutiao…); CN and Global measured separately |
| **Scoring basis** | Heuristics | Anchored in public empirical data: 602 prompts / 21,143 citations / 187,818 deduplicated CN citations ([references/](references/)) |
| **Data ownership** | Vendor cloud | **Everything on your machine** under `work/` (JSON/Markdown); `git init` is your backup |
| **Cost** | Subscription | Free and open source; you only pay your own engine API sampling costs (can be zero — manual sampling works) |
| **Deliverables** | Dashboard screenshots | Client-ready diagnosis report / strategy / execution plan / ticket CSV — built for agencies and consultants |

Honest limits: single-machine tool, no accounts or team collaboration; sampling frequency and volume depend on your own API budget; "suspected negative" flags are leads for human review, not verdicts. These are deliberate design choices.

## 4. Deployment

### Requirements

- macOS or Linux (Windows via WSL — the code uses `fcntl` file locks)
- Python **3.9+**
- Exactly three third-party packages: `requests`, `beautifulsoup4`, `lxml`

### Three steps

```bash
# 1. Clone and install
git clone https://github.com/aigclink/geolook.git
cd geolook
pip3 install requests beautifulsoup4 lxml

# 2. Start the dashboard (opens your browser)
python3 scripts/geo.py ui        # → http://127.0.0.1:8765
#    macOS: ./scripts/service.sh install registers it as a standing service
#    (starts at login, restarts on crash, survives closing every terminal)

# 3. (Optional) Configure engine API keys
#    A: in the dashboard — Settings → Engines & Keys → "Configure" (writes local .env)
#    B: cp .env.example .env and edit
```

**Zero keys works too**: automated sampling is skipped; use the manual sampling sheet loop instead. Crawling, auditing, tickets and assets need no keys. One CN-capable key (e.g. DeepSeek/GLM) unlocks auto-derivation of the question bank / brand facts and AI first drafts.

### Remote / server deployment

The server binds to `127.0.0.1` only (a deliberate security boundary — there is no auth layer). For remote access:

```bash
ssh -N -L 8765:127.0.0.1:8765 user@your-server   # then open http://127.0.0.1:8765 locally
```

For multi-user setups put a reverse proxy with auth in front. `.env` and `work/` contain secrets and project data — mind file permissions.

### Upgrading

```bash
git pull        # your data lives in work/ and .env, both gitignored
```

## 5. Usage

### Route A: fully automated (10–30 min)

```bash
python3 scripts/geo.py new --url https://example.com --market both
```

`--market` is `cn` / `global` / `both`. Nine steps run automatically: crawl → audit → derive facts/competitors/questions → sample every engine → tickets → assets → report → auto-verify → delivery package, landing in `work/<slug>/delivery/<date>/`.

### Route B: dashboard walkthrough (recommended first time)

1. **Onboard** — `python3 scripts/geo.py ui`, follow the 3-step wizard (URL + market), hit "create & auto-bootstrap". The first cycle runs in the background.
2. **Review the foundation** (important, ~10 min) — facts are extracted only from your site copy; unknowns are marked "unconfirmed". Check **Brand Facts** (fix wording, add aliases — missing aliases understate mention rate) and the **Question Bank** (do questions read like real user queries?).
3. **Status** — Overview for the one-line verdict and health score; **Engines** to drill into each engine and replay raw answers (log factual errors on the spot); **Competitors** to see each rival's strongest engine — that's the channel to go build.
4. **Diagnosis** — Site audit (click a missing block → its fixing ticket) → Gap diagnosis → Channel map (open any channel for its build plan).
5. **Execute** — Take tickets P0-first in **Action Plan** (click a title for why/how/acceptance); write in the **Workbench** (pre-check ≥ B, publish as final, then work through the distribution checklist); deploy **Assets** (llms.txt to site root, JSON-LD into `<head>`, snippets into templates — see DEPLOY.md).
6. **Verify** — Settings → "Auto-verify" re-crawls and judges tickets; after the next sampling round, check per-question before/after in **Verification**.
7. **Operate** — enable scheduled re-runs (7/14/30 days); generate monthly reports and client packages in **Reports & Delivery**.

### Manual sampling for engines without APIs

```bash
python3 scripts/geo.py sample-sheet  --slug <project>                      # full sheet
python3 scripts/geo.py sample-sheet  --slug <project> --intent buyer --limit 20   # weekly buyer-intent check
python3 scripts/geo.py sample-import --slug <project> --file <sheet>
```

Faster: install the Chrome sampling assistant (`extension/README.md`) and launch a clean sandbox with `extension/sandbox.sh` — queue, one-click extraction and upload, ~10 minutes per weekly round. Review imported samples in the dashboard's **Samples** page (machine parsing is correctable there; corrections recompute metrics instantly).

### CLI cheat sheet

| Command | Purpose |
|---|---|
| `new` / `serve` / `cycle` | Automated new project / full cycle / light loop |
| `ui` | Full-workflow dashboard |
| `bootstrap` / `crawl` / `audit` | Derive foundation / crawl / 6-dimension scoring |
| `sample` / `sample-sheet` / `sample-import` | API sampling / manual sheets |
| `plan` / `generate` / `lint` | Tickets / assets (`--draft` adds drafts) / fabrication-risk check |
| `verify` / `report` / `deliverables` / `deliver` | Auto-verify / reports / formal deliverables / client package |
| `publish` / `task` / `status` / `list` | Publish content / ticket status / project board / projects |

Every command has `--help`.

## FAQ

**Q: AI answers differ every time — how can sampling results be stable?**

A single AI answer is inherently stochastic, so GeoLook **never reads a single answer** as a metric. Stability comes from four layers:

1. **Aggregation** — mention rate and friends are ratios over dozens of questions × multiple engines; per-question jitter averages out.
2. **Fixed variables** — each engine's sampling model is pinned (visible and changeable in Settings), the question bank is fixed, and the same set is reused across rounds; the only thing that changes is time.
3. **Repeat rounds** — `sample --repeat N` samples each question multiple times when your budget allows.
4. **Attribution discipline** — the UI explicitly labels single-round movement as observational ("a drop isn't necessarily a regression — sampling is noisy"); only two consecutive rounds moving the same way count as a trend, and ticket verification relies on deterministic signals (re-crawling the site) rather than sampling alone.

Honestly put: it measures a **distribution**, not a fixed value — which is exactly what real users experience, since every real query to an AI engine draws a random sample too.

## Evidence-based scoring

All six audit dimensions are anchored in public empirical data; `scripts/audit.py` implements [references/method.md](references/method.md):

- High-impact pages average **1,943 words**; low scorers just 170 (11.4×)
- Numbers **+61.6%**, definitions **+57.3%**, comparisons **+55.3%**, how-to **+41.2%** citation-probability lift
- Pure Q&A formatting is **−5.7%** — looking like an FAQ doesn't help
- Topical relevance is the strongest predictor (r = 0.432), above authority
- Brand-owned sites get only **1.37%** of CN citations — your site is the fact source; external channels are the citation sources

## Design principles & security boundaries

- **Single-machine, self-hosted**: stdlib `http.server` on 127.0.0.1; no DB, no accounts; data is plain files
- **Never fabricate**: facts only from site copy; inventing competitor names is forbidden; AI drafts must pass lint + human review
- **Verification is the product**: anything auto-verifiable never relies on someone saying "done"
- **Publishing is always manual**: channel credentials in local `.env` (mode 600); every publish is an explicit click; WeChat/WordPress go to drafts only

## Claude Code integration (optional)

This repo doubles as a Claude Code skill ([SKILL.md](SKILL.md)): drop it into your skills directory and tell Claude "do GEO for example.com". Claude is optional — every script is a plain CLI.

## Layout

```
scripts/          All logic (geo.py CLI · dashboard.py server · ui.html single-page UI · service.sh)
extension/        Chrome sampling assistant + sandbox.sh + its own e2e tests
references/       Methodology: sampling discipline, content patterns, attribution, citation structures
tests/            Unit tests
work/<slug>/      Per-project data (gitignored, never leaves your machine)
docs/             Screenshots and the 40-second demo video
```

## Acknowledgements

- [@yaojingang](https://github.com/yaojingang)

## Contact

Questions, ideas or collaboration — email [bingqiang2008@gmail.com](mailto:bingqiang2008@gmail.com), or open an [issue](https://github.com/aigclink/geolook/issues).

## License

[MIT](LICENSE)
