// GeoLook 采样助手 · 侧边栏
// 流程：载入队列 → 选题 → 填入问题(人按回车) → 答案生成完 → 提取 → 保存 → 上传/导出。

const $ = (s) => document.querySelector(s);
let QUEUE = { questions: [], platforms: [], groups: [] };
let SEL = null;            // 选中的题
let LAST = null;           // 最近一次提取结果
let SAMPLES = [];          // 已采集未上传
let GROUPS = [];           // 选中的意图分组（空 = 全部）

// 站点 → 平台码。识别不了的站让用户在下拉里自己选（下拉来自服务端平台清单）。
const HOST2PLAT = {
  "chatgpt.com": "chatgpt", "chat.openai.com": "chatgpt",
  "claude.ai": "claude_web",
  "doubao.com": "doubao_app",
  "google.com": "google_aio",
  "chat.baidu.com": "baidu", "yiyan.baidu.com": "baidu", "wenxin.baidu.com": "baidu",
  "metaso.cn": "metaso", "n.cn": "nano_ai",
  "n.cn": "nano_ai", "bot.n.cn": "nano_ai",
};

const store = {
  async get(k, d) { const o = await chrome.storage.local.get(k); return o[k] ?? d; },
  async set(k, v) { await chrome.storage.local.set({ [k]: v }); },
};

function serverUrl() { return $("#server").value.trim().replace(/\/$/, "") || "http://127.0.0.1:8765"; }
function slug() { return $("#slug").value; }

async function apiGet(path) {
  const r = await fetch(serverUrl() + path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function activeTab() {
  const [tab] = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  return tab || null;
}

// 采样环境说明。国内引擎多数必须登录，无痕并非总是可行——
// 关键不是「有没有开无痕」，而是「这批样本是在什么环境采的、有没有如实记录」。
const SESSION_NOTE = {
  sandbox: "由 extension/sandbox.sh 起的一次性沙箱：无历史、无 Cookie、未登录，关掉即清除。免登录引擎（百度AI搜索、Google AI Overviews、秘塔、Perplexity 游客态）用这个最干净。",
  incognito: "无痕 + 未登录，最接近陌生买家看到的答案。注意无痕默认禁用扩展（需在 chrome://extensions 里单独授权），且关窗后未上传的样本会丢失。",
  clean_profile: "专用 Chrome Profile：只用于采样，从不搜自己品牌、不点自己官网，并关掉各家的记忆/个性化开关。需要登录的豆包/Kimi/元宝/ChatGPT 用这个。",
  personal: "你的日常账号带着历史与个性化，测出来的是「AI 对你的画像」。这类样本会自动降级为「待复核」，不计入可信的可见性证据。",
};

function sessionMode() { return $("#session").value || "sandbox"; }

async function refreshDiscipline() {
  const el = $("#discipline"), sm = sessionMode();
  $("#sesnote").textContent = SESSION_NOTE[sm];
  const tab = await activeTab();
  const warns = [];
  // 只有选了「无痕」却不在无痕窗口时才报警——选专用 Profile 时无痕本来就不适用
  if (sm === "incognito" && tab && !tab.incognito)
    warns.push("你选的是「无痕未登录」，但当前不是无痕窗口——要么换无痕窗口，要么把上面的采样环境改成实际用的那个");
  if (sm === "personal")
    warns.push("个人日常账号采集：样本会标为「待复核」，别用它下可见性结论");
  warns.push("每题新开对话，不连续追问；答案没提到品牌也照样保存");
  el.hidden = false;
  el.innerHTML = warns.map(w => "· " + w).join("<br>");
  el.style.display = warns.length > 1 ? "" : "none";
}

async function detectPlatform() {
  const tab = await activeTab();
  let code = "";
  if (tab && tab.url) {
    try { code = HOST2PLAT[new URL(tab.url).hostname.replace(/^www\./, "")] || ""; } catch (e) {}
  }
  const known = QUEUE.platforms.find(p => p.code === code);
  $("#plat").textContent = known ? known.label : (code || "未识别");
  if (known) $("#platSel").value = code;
}

function currentPlatform() {
  return $("#platSel").value || "";
}

function collectedKey(p, qid) { return `${p}::${qid}`; }

async function renderQueue() {
  const doneSet = new Set(SAMPLES.map(s => collectedKey(s.platform, s.question_id)));
  const p = currentPlatform();
  // 按分组分节渲染：同一类问题连着采，人的思路不用来回切换
  const byGroup = {};
  QUEUE.questions.forEach(q => (byGroup[q.group || "未分组"] = byGroup[q.group || "未分组"] || []).push(q));
  const sections = Object.entries(byGroup).map(([g, list]) => {
    const left = list.filter(q => !doneSet.has(collectedKey(p, q.id))).length;
    return `<div class="small" style="color:var(--t600);margin:8px 0 2px">${g}
        <span style="color:var(--t500)">· 待采 ${left}/${list.length}</span></div>` +
      list.map(q => `
        <div class="q ${SEL && SEL.id === q.id ? "sel" : ""}" data-id="${q.id}">
          <span class="id">${q.id}</span>${q.text}
          ${doneSet.has(collectedKey(p, q.id)) ? '<span class="done">✓ 已采</span>' : ""}
        </div>`).join("");
  }).join("");
  $("#qlist").innerHTML = sections || '<div class="muted" style="padding:8px">先点「载入队列」</div>';
  document.querySelectorAll(".q").forEach(el => el.onclick = () => {
    SEL = QUEUE.questions.find(x => x.id === el.dataset.id);
    renderQueue();
  });
  $("#qmeta").textContent = QUEUE.questions.length
    ? `${QUEUE.brand} · ${QUEUE.questions.length} 题${GROUPS.length ? "（" + GROUPS.join("/") + "）" : ""}` : "";
}

async function loadProjects() {
  try {
    const ps = await apiGet("/api/projects");
    $("#slug").innerHTML = ps.map(p => `<option value="${p.slug}">${p.name}</option>`).join("");
    const saved = await store.get("slug");
    if (saved && ps.some(p => p.slug === saved)) $("#slug").value = saved;
  } catch (e) {
    $("#qmeta").textContent = "连不上看板——先启动 geo.py ui";
  }
}

function renderGroups() {
  $("#groups").innerHTML = (QUEUE.groups || []).map(g => `
    <span class="chip ${GROUPS.includes(g.name) ? "on" : ""} ${g.buyer ? "buyer" : ""}"
      data-g="${g.name}" title="${g.buyer ? "买家意图组——离成交最近" : "需求教育/探测组"}">${g.name}<span class="n">${g.count}</span></span>`).join("");
  document.querySelectorAll(".chip").forEach(el => el.onclick = async () => {
    const g = el.dataset.g;
    GROUPS = GROUPS.includes(g) ? GROUPS.filter(x => x !== g) : GROUPS.concat(g);
    await store.set("groups", GROUPS);
    loadQueue();
  });
}

async function loadQueue() {
  try {
    const qp = new URLSearchParams({ limit: "40" });
    if (GROUPS.length) qp.set("groups", GROUPS.join(","));
    else qp.set("intent", "buyer");     // 没选过分组时默认买家意图，和周检表口径一致
    QUEUE = await apiGet(`/api/collect/queue/${slug()}?${qp}`);
    if (!GROUPS.length && QUEUE.selected && QUEUE.selected.length) GROUPS = QUEUE.selected;
    await store.set("slug", slug());
    $("#platSel").innerHTML = QUEUE.platforms
      .map(p => `<option value="${p.code}">${p.label}</option>`).join("");
    await detectPlatform();
    renderGroups();
    SEL = QUEUE.questions[0] || null;
    renderQueue();
  } catch (e) {
    $("#qmeta").textContent = "加载失败：" + e.message;
  }
}

async function sendToTab(msg) {
  const tab = await activeTab();
  if (!tab) return { ok: false, error: "找不到活动标签页" };
  try { return await chrome.tabs.sendMessage(tab.id, msg); }
  catch (e) { return { ok: false, error: "此页面没有采样脚本（站点不在支持列表，或需刷新页面）" }; }
}

$("#load").onclick = loadQueue;
$("#platSel").onchange = renderQueue;
$("#pickbuyer").onclick = async () => {
  GROUPS = (QUEUE.groups || []).filter(g => g.buyer).map(g => g.name);
  await store.set("groups", GROUPS); loadQueue();
};
$("#pickall").onclick = async () => {
  GROUPS = (QUEUE.groups || []).map(g => g.name);
  await store.set("groups", GROUPS); loadQueue();
};

$("#copy").onclick = async () => {
  if (!SEL) return;
  await navigator.clipboard.writeText(SEL.text);
  $("#exmeta").textContent = "已复制，去页面粘贴提问";
};

$("#fill").onclick = async () => {
  if (!SEL) return;
  const r = await sendToTab({ type: "geolook-fill", text: SEL.text });
  if (!r.ok) { await navigator.clipboard.writeText(SEL.text); }
  $("#exmeta").textContent = r.ok ? "已填入输入框——检查后自己按回车" : (r.error || "填入失败，已复制到剪贴板");
};

$("#extract").onclick = async () => {
  if (!SEL) { $("#exmeta").textContent = "先选一道题"; return; }
  const r = await sendToTab({ type: "geolook-extract" });
  if (!r.ok) { $("#exmeta").textContent = r.error || "提取失败"; $("#save").disabled = true; return; }
  LAST = r;
  $("#preview").hidden = false;
  $("#preview").textContent = r.answer.slice(0, 800) + (r.answer.length > 800 ? " …" : "");
  $("#exmeta").innerHTML = `<span class="okline">${r.mode === "selection" ? "选区提取" : "自动提取"} · ${r.answer.length} 字 · 引用 ${r.citations.length} 条</span>`;
  $("#save").disabled = false;
};

$("#save").onclick = async () => {
  if (!LAST || !SEL) return;
  const plat = currentPlatform();
  if (!plat) { $("#exmeta").textContent = "先在右上下拉选择当前引擎"; return; }
  SAMPLES = SAMPLES.filter(s => !(s.platform === plat && s.question_id === SEL.id));
  SAMPLES.push({ platform: plat, question_id: SEL.id, question: SEL.text,
                 answer: LAST.answer, citations: LAST.citations, page_url: LAST.url,
                 session_mode: sessionMode(), ts: new Date().toISOString() });
  await store.set("samples:" + slug(), SAMPLES);
  LAST = null; $("#save").disabled = true; $("#preview").hidden = true;
  $("#exmeta").textContent = "已保存。下一题：新开对话再问。";
  // 自动跳到下一道未采的题
  const done = new Set(SAMPLES.map(s => collectedKey(s.platform, s.question_id)));
  SEL = QUEUE.questions.find(q => !done.has(collectedKey(plat, q.id))) || SEL;
  $("#count").textContent = SAMPLES.length;
  renderQueue();
};

/* ---------------- 自动跑队列 ----------------
   人在场、小批量、限速、异常即停。这是「替你操作」，不是「无人值守爬取」：
   侧栏关掉就停、切走标签页就停、撞到验证码/风控立刻停并交回给人。*/
let RUN = null;

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
function alog(msg, cls) {
  const el = document.createElement("div");
  el.className = cls || "";
  el.textContent = `${new Date().toTimeString().slice(0, 5)} ${msg}`;
  $("#autolog").prepend(el);
}

async function waitAnswer(tabId, timeoutMs) {
  const t0 = Date.now();
  while (Date.now() - t0 < timeoutMs) {
    if (!RUN) return { state: "aborted" };
    await sleep(1500);
    let s;
    try { s = await chrome.tabs.sendMessage(tabId, { type: "geolook-status", stableMs: 2500 }); }
    catch (e) { continue; }              // 导航中，重试
    if (!s) continue;
    if (s.state === "blocked") return s;
    if (s.state === "done") return s;
  }
  return { state: "timeout" };
}

async function autoRun() {
  const plat = currentPlatform();
  if (!plat) { alog("先在上方选择当前引擎", "okline"); return; }
  const tab = await activeTab();
  if (!tab) return;
  if (sessionMode() === "incognito" && !tab.incognito &&
      !confirm("采样环境选的是「无痕未登录」，但当前不是无痕窗口。\n继续的话样本环境标记会与实际不符——建议先改上面的采样环境。仍要继续吗？")) return;
  const ivl = Math.max(10, +$("#ivl").value || 25) * 1000;
  const cap = Math.max(1, Math.min(30, +$("#cap").value || 20));
  const done = new Set(SAMPLES.map(s => collectedKey(s.platform, s.question_id)));
  const todo = QUEUE.questions.filter(q => !done.has(collectedKey(plat, q.id))).slice(0, cap);
  if (!todo.length) { alog("这个引擎的队列已采完"); return; }
  if (!confirm(`将在当前标签页自动提问 ${todo.length} 题（每题间隔 ${ivl / 1000}s）。\n请全程留在页面上；随时可点「中止」。`)) return;

  RUN = { tabId: tab.id, plat, total: todo.length, i: 0, fails: 0 };
  $("#auto").hidden = true; $("#abort").hidden = false;
  alog(`开始：${todo.length} 题 · ${plat}${GROUPS.length ? " · " + GROUPS.join("/") : ""}`);

  for (const q of todo) {
    if (!RUN) break;
    RUN.i++;
    // 每题新开会话：连续追问会让上文污染后面的答案
    try {
      const nc = await chrome.tabs.sendMessage(RUN.tabId, { type: "geolook-newchat" });
      if (nc && nc.url) { await chrome.tabs.update(RUN.tabId, { url: nc.url }); await sleep(3500); }
    } catch (e) { /* 站点不在映射表，就地继续 */ }
    if (!RUN) break;

    let sent;
    try { sent = await chrome.tabs.sendMessage(RUN.tabId, { type: "geolook-submit", text: q.text }); }
    catch (e) { sent = { ok: false, error: "页面无采样脚本" }; }
    if (!sent || !sent.ok) {
      RUN.fails++; alog(`[${RUN.i}/${RUN.total}] ${q.id} 提交失败：${(sent && sent.error) || "未知"}`);
      if (RUN.fails >= 2) { alog("连续失败 2 次，已停止", "okline"); break; }
      continue;
    }
    alog(`[${RUN.i}/${RUN.total}] ${q.id} 已提交，等待生成…`);

    const st = await waitAnswer(RUN.tabId, 120000);
    if (!RUN) break;
    if (st.state === "blocked") { alog("⚠ " + st.reason + " —— 已停止，请人工处理", "okline"); break; }
    if (st.state !== "done") { RUN.fails++; alog(`[${RUN.i}] 超时未拿到答案`); if (RUN.fails >= 2) break; continue; }

    let ex;
    try { ex = await chrome.tabs.sendMessage(RUN.tabId, { type: "geolook-extract" }); }
    catch (e) { ex = { ok: false, error: "提取失败" }; }
    if (!ex || !ex.ok) { RUN.fails++; alog(`[${RUN.i}] ${ex && ex.error}`); if (RUN.fails >= 2) break; continue; }

    RUN.fails = 0;
    SAMPLES = SAMPLES.filter(s => !(s.platform === plat && s.question_id === q.id));
    SAMPLES.push({ platform: plat, question_id: q.id, question: q.text, answer: ex.answer,
                   citations: ex.citations, page_url: ex.url,
                   session_mode: sessionMode(), ts: new Date().toISOString() });
    await store.set("samples:" + slug(), SAMPLES);
    $("#count").textContent = SAMPLES.length;
    renderQueue();
    alog(`[${RUN.i}/${RUN.total}] ✓ ${ex.answer.length} 字 · 引用 ${ex.citations.length}`, "okline");
    if (RUN.i < RUN.total) await sleep(ivl + Math.random() * 4000);
  }

  const finished = RUN ? RUN.i : 0;
  RUN = null;
  $("#auto").hidden = false; $("#abort").hidden = true;
  alog(`结束：本轮 ${finished} 题，已采集 ${SAMPLES.length} 条。检查无误后点「上传到 GeoLook」。`, "okline");
}

$("#auto").onclick = autoRun;
$("#abort").onclick = () => { RUN = null; alog("已中止"); $("#auto").hidden = false; $("#abort").hidden = true; };

$("#upload").onclick = async () => {
  if (!SAMPLES.length) { $("#upmsg").textContent = "还没有已采集的样本"; return; }
  try {
    const r = await fetch(`${serverUrl()}/api/collect/${slug()}`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ records: SAMPLES }),
    });
    const j = await r.json();
    if (j.ok) {
      $("#upmsg").textContent = `✓ 已导入 ${j.imported} 条（A 级人工样本），指标已重算`;
      SAMPLES = []; await store.set("samples:" + slug(), []);
      $("#count").textContent = "0"; renderQueue();
    } else $("#upmsg").textContent = "导入失败：" + (j.error || r.status);
  } catch (e) { $("#upmsg").textContent = "连不上看板：" + e.message; }
};

$("#export").onclick = () => {
  if (!SAMPLES.length) return;
  const byPlat = {};
  SAMPLES.forEach(s => (byPlat[s.platform] = byPlat[s.platform] || []).push(s));
  let md = `# ${QUEUE.brand || slug()} · 插件采样导出 · ${new Date().toISOString().slice(0, 10)}\n\n`;
  for (const [p, list] of Object.entries(byPlat)) {
    md += `## platform: ${p}\n\n`;
    for (const s of list) {
      const cites = s.citations.map(c => `- ${c.url} ${c.title}`).join("\n");
      md += `### ${s.question_id} · ${s.question}\n\n\`\`\`answer\n${s.answer}\n${cites ? "\n引用：\n" + cites + "\n" : ""}\`\`\`\n\n`;
    }
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([md], { type: "text/markdown" }));
  a.download = `geolook-samples-${Date.now()}.md`;
  a.click();
};

$("#session").onchange = async () => {
  await store.set("session", sessionMode());
  refreshDiscipline();
};

(async () => {
  await loadProjects();
  $("#session").value = await store.get("session", "sandbox");
  GROUPS = await store.get("groups", []);
  SAMPLES = await store.get("samples:" + slug(), []);
  $("#count").textContent = SAMPLES.length;
  await refreshDiscipline();
  chrome.tabs.onActivated.addListener(() => { refreshDiscipline(); detectPlatform(); });
  chrome.tabs.onUpdated.addListener((_, info) => { if (info.status === "complete") { refreshDiscipline(); detectPlatform(); } });
})();
