// GeoLook 采样助手 · 页面侧
// 只做两件事：① 提取已渲染的答案与引用（读，不写）② 把问题填进输入框（不代发）。
// 没有任何自动提交、自动翻页、定时任务。

(() => {
  if (window.__geolookCollector) return;
  window.__geolookCollector = true;

  const HOST = location.hostname.replace(/^www\./, "");

  // 每站的「答案容器」候选选择器，从前往后试；全部失败退回通用启发式。
  // 选择器会随各家改版失效——失效时提取降级为「选中文本」，功能不消失。
  const ANSWER_SELECTORS = {
    "chatgpt.com": ['[data-message-author-role="assistant"]'],
    "chat.openai.com": ['[data-message-author-role="assistant"]'],
    "claude.ai": ['[data-testid="assistant-message"]', ".font-claude-message"],
    "doubao.com": ['[data-testid="receive_message"]', '[class*="message-content"]'],
    "perplexity.ai": ['[data-testid="answer"]', ".prose", '[class*="prose"]'],
    "gemini.google.com": ["message-content", '[class*="model-response"]'],
    "google.com": ['[data-attrid="AIOverview"]', '[aria-label*="AI 概览"]', '[aria-label*="AI Overview"]'],
    "chatglm.cn": ['[class*="answer"]', '[class*="markdown"]'],
    "kimi.com": ['[class*="segment-assistant"]', '[class*="markdown"]'],
    "kimi.moonshot.cn": ['[class*="segment-assistant"]', '[class*="markdown"]'],
    "yuanbao.tencent.com": ['[class*="agent-chat__bubble--ai"]', '[class*="markdown"]'],
    "yiyan.baidu.com": ['[class*="answer_text"]', '[class*="markdown"]'],
    "chat.baidu.com": ['[class*="answer"]', '[class*="markdown"]'],
    // chat.baidu.com 实测会重定向到 wenxin.baidu.com（百度文心助手）
    "wenxin.baidu.com": ['[class*="answer"]', '[class*="markdown"]'],
    "n.cn": ['[class*="answer"]', '[class*="markdown"]'],
    "bot.n.cn": ['[class*="answer"]', '[class*="markdown"]'],
    "metaso.cn": ['[class*="answer"]', '[class*="markdown"]'],
  };

  // 输入框候选。手动模式下只填入不发送；自动模式（用户显式开启）才会发送。
  // #ask-input 是 Perplexity 实测的稳定 id。
  const INPUT_SELECTORS = [
    "#prompt-textarea",
    "#ask-input",
    'div[contenteditable="true"][role="textbox"]',
    "textarea:not([readonly]):not([disabled])",
    'div[contenteditable="true"]',
  ];

  // 发送按钮候选：优先点按钮，找不到再回退到回车键
  const SEND_SELECTORS = [
    '[data-testid="send-button"]',
    'button[aria-label*="发送"]',
    'button[aria-label*="Send"]',
    'button[type="submit"]:not([disabled])',
    '[class*="send-btn"]:not([disabled])',
  ];

  // 出现这些就立刻停：验证码、风控、限流。自动模式撞到任何一条都必须交回给人。
  const BLOCK_CUES = /(验证码|人机验证|安全验证|请稍后再试|访问过于频繁|滑动验证|captcha|verify you are human|unusual activity|rate limit|too many requests)/i;

  // 新会话入口：每题独立上下文是采样纪律，不能在同一对话里连续问
  const NEWCHAT = {
    "chatgpt.com": "https://chatgpt.com/",
    "chat.openai.com": "https://chat.openai.com/",
    "claude.ai": "https://claude.ai/new",
    "doubao.com": "https://www.doubao.com/chat/",
    "perplexity.ai": "https://www.perplexity.ai/",
    "gemini.google.com": "https://gemini.google.com/app",
    "chatglm.cn": "https://chatglm.cn/main/alltoolsdetail",
    "kimi.com": "https://kimi.com/",
    "kimi.moonshot.cn": "https://kimi.moonshot.cn/",
    "yuanbao.tencent.com": "https://yuanbao.tencent.com/chat/naQivTmsDa",
    "metaso.cn": "https://metaso.cn/",
    "wenxin.baidu.com": "https://wenxin.baidu.com/",
  };

  function visible(el) {
    const r = el.getBoundingClientRect();
    return r.width > 40 && r.height > 10;
  }

  // 站点没适配时的通用容器特征（各家聊天 UI 的类名/属性习惯高度趋同）
  const GENERIC_SELECTORS = [
    '[data-message-author-role="assistant"]',
    '[class*="assistant"]',
    '[class*="markdown"]',
    '[class*="answer"]',
    '[class*="message-content"]',
  ];

  function pickAnswerEl() {
    // 所有候选选择器各取「最后一个可见元素」（最新回答），再从中选文本最长的。
    // 不能按选择器顺序取第一个命中——实测秘塔的 [class*="answer"] 会撞上 6 字的
    // 无关元素，按序取会把它当答案；按最长取则撞词容器自动被淘汰。
    let best = null, bestLen = 0;
    for (const sel of (ANSWER_SELECTORS[HOST] || []).concat(GENERIC_SELECTORS)) {
      const list = [...document.querySelectorAll(sel)].filter(visible);
      if (!list.length) continue;
      const el = list[list.length - 1];
      const len = (el.innerText || "").length;
      if (len > bestLen) { best = el; bestLen = len; }
    }
    if (best) return best;
    // 兜底：main/article 里文本最长的容器。不设长度门槛——短答案同样要能被检测到，
    // 「够不够长」由 status/extract 各自的 40 字下限判断。
    for (const root of document.querySelectorAll("main, article")) {
      const t = (root.innerText || "").length;
      if (t > bestLen) { best = root; bestLen = t; }
    }
    return best;
  }

  function extractCitations(scope) {
    const seen = new Set();
    const out = [];
    for (const a of scope.querySelectorAll('a[href^="http"]')) {
      let href = a.href;
      try {
        const u = new URL(href);
        if (u.hostname.replace(/^www\./, "") === HOST) continue; // 站内导航不算引用
        href = u.origin + u.pathname + u.search;
      } catch (e) { continue; }
      if (seen.has(href)) continue;
      seen.add(href);
      const title = (a.getAttribute("title") || a.innerText || "").trim().slice(0, 200);
      out.push({ url: href.slice(0, 500), title });
      if (out.length >= 30) break;
    }
    return out;
  }

  function extract() {
    // 用户选中了文本 → 以选区为准（最可靠的降级路径，任何站都可用）
    const sel = window.getSelection();
    if (sel && sel.toString().trim().length > 40) {
      const range = sel.getRangeAt(0);
      const scope = range.commonAncestorContainer.nodeType === 1
        ? range.commonAncestorContainer
        : range.commonAncestorContainer.parentElement;
      return { ok: true, mode: "selection", answer: sel.toString().trim(),
               citations: scope ? extractCitations(scope) : [] };
    }
    const el = pickAnswerEl();
    if (!el) return { ok: false, error: "没找到答案容器——请选中答案文本后重试" };
    const answer = (el.innerText || "").trim();
    if (answer.length < 40) return { ok: false, error: "答案内容太短——可能还没生成完，或需要选中文本提取" };
    return { ok: true, mode: "auto", answer, citations: extractCitations(el) };
  }

  function inputEl() {
    for (const sel of INPUT_SELECTORS) {
      const el = [...document.querySelectorAll(sel)].filter(visible).pop();
      if (el) return el;
    }
    return null;
  }

  function fill(text) {
    const el = inputEl();
    if (!el) return { ok: false, error: "没找到输入框——已复制到剪贴板，请手动粘贴" };
    el.focus();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const setter = Object.getOwnPropertyDescriptor(
        el.tagName === "TEXTAREA" ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, "value").set;
      setter.call(el, text);
    } else {
      el.textContent = text;
    }
    el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text }));
    return { ok: true };
  }

  // 仅自动模式调用：填入后发送。用户必须先在侧栏显式开启自动跑队列。
  function submit(text) {
    const f = fill(text);
    if (!f.ok) return f;
    const el = inputEl();
    for (const sel of SEND_SELECTORS) {
      const btn = [...document.querySelectorAll(sel)].filter(visible).pop();
      if (btn && !btn.disabled) { btn.click(); return { ok: true, via: "button" }; }
    }
    for (const type of ["keydown", "keypress", "keyup"]) {
      el.dispatchEvent(new KeyboardEvent(type, {
        key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true,
      }));
    }
    return { ok: true, via: "enter" };
  }

  // 答案是否生成完：文本连续 stableMs 毫秒不再增长即认为收笔。
  // 同时检查风控线索——命中就报 blocked，由侧栏中止整轮。
  let watch = null;
  function status(stableMs) {
    const body = document.body ? document.body.innerText || "" : "";
    if (BLOCK_CUES.test(body.slice(0, 4000))) return { state: "blocked", reason: "页面出现验证码/风控提示" };
    const el = pickAnswerEl();
    const text = el ? (el.innerText || "") : "";
    const now = Date.now();
    if (!watch || watch.len !== text.length) watch = { len: text.length, at: now };
    if (text.length < 40) return { state: "waiting", len: text.length };
    return { state: now - watch.at >= (stableMs || 2500) ? "done" : "streaming", len: text.length };
  }

  chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg) return false;
    if (msg.type === "geolook-extract") sendResponse({ host: HOST, url: location.href, ...extract() });
    else if (msg.type === "geolook-fill") sendResponse(fill(String(msg.text || "")));
    else if (msg.type === "geolook-submit") { watch = null; sendResponse(submit(String(msg.text || ""))); }
    else if (msg.type === "geolook-status") sendResponse(status(msg.stableMs));
    else if (msg.type === "geolook-newchat") sendResponse({ ok: true, url: NEWCHAT[HOST] || "" });
    return false;
  });
})();
