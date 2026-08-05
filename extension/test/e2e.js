// 插件 + 沙箱闭环端到端测试：真实 Chrome 扩展运行时 + 真实 content script 注入 + 真实看板。
// 用 Chrome for Testing（仍支持 --load-extension）加载扩展副本（manifest 加上 fixture 域名）。
process.env.NODE_PATH = require("child_process").execSync("npm root -g").toString().trim();
require("module")._initPaths();
const { chromium } = require("playwright-core");
const fs = require("fs"), path = require("path"), os = require("os");

const SRC = path.resolve(__dirname, "..");
const CFT = os.homedir() + "/Library/Caches/ms-playwright/chromium-1228/chrome-mac-arm64/" +
  "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing";
const FIXTURE = "http://localhost:8614/test/fixture.html";
const DASH = "http://127.0.0.1:8765";
const ok = (c, m) => console.log((c ? "  ✓ " : "  ✗ ") + m);

(async () => {
  // 1. 复制扩展并把 fixture 域名加进 matches（只影响测试副本，不改仓库代码）
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "geolook-ext-"));
  for (const f of ["manifest.json", "background.js", "content.js", "sidepanel.html", "sidepanel.js"])
    fs.copyFileSync(path.join(SRC, f), path.join(dir, f));
  const mf = JSON.parse(fs.readFileSync(path.join(dir, "manifest.json"), "utf8"));
  mf.content_scripts[0].matches.push("http://localhost:8614/*");
  fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(mf, null, 2));

  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "geolook-sandbox-"));
  const ctx = await chromium.launchPersistentContext(profile, {
    executablePath: CFT, headless: false,
    args: [`--load-extension=${dir}`, `--disable-extensions-except=${dir}`,
           "--no-first-run", "--no-default-browser-check",
           "--window-position=-3000,-3000", "--window-size=900,700"],
  });

  console.log("【1】扩展运行时");
  let sw = ctx.serviceWorkers().find(w => w.url().includes("background.js"));
  if (!sw) sw = await ctx.waitForEvent("serviceworker", { timeout: 15000 });
  const extId = new URL(sw.url()).host;
  ok(!!extId, `service worker 已启动，扩展 id=${extId.slice(0, 12)}…`);

  console.log("【2】content script 自动注入");
  const page = await ctx.newPage();
  await page.goto(FIXTURE, { waitUntil: "domcontentloaded" });
  await page.waitForTimeout(1500);
  // content script 跑在隔离世界，page.evaluate（主世界）看不到它的全局标记；
  // 用扩展 → 标签页的真实消息通道验证，这也正是插件实际用的路径
  const pong = await sw.evaluate(async () => {
    const tabs = await chrome.tabs.query({ url: "http://localhost:8614/*" });
    if (!tabs.length) return { err: "没找到目标标签页" };
    try { return await chrome.tabs.sendMessage(tabs[0].id, { type: "geolook-status", stableMs: 100 }); }
    catch (e) { return { err: String(e) }; }
  });
  ok(pong && pong.state, `打开引擎页面后 content script 自动注入并响应消息（state=${pong && (pong.state || pong.err)}）`);

  console.log("【3】侧栏页面加载 + 连接看板");
  const side = await ctx.newPage();          // 独立窗口模拟侧栏，与被采页面并存
  await side.goto(`chrome-extension://${extId}/sidepanel.html`);
  await side.waitForTimeout(1200);
  const slugOpts = await side.$$eval("#slug option", els => els.map(e => e.value));
  ok(slugOpts.includes("aigclink"), `读到项目列表：${slugOpts.join(",")}`);

  await side.click("#load");
  await side.waitForTimeout(1200);
  const chips = await side.$$eval(".chip", els => els.map(e => e.textContent.trim()));
  ok(chips.length >= 5, `分组芯片渲染：${chips.join(" ")}`);
  const qcount = await side.$$eval(".q", els => els.length);
  ok(qcount > 0, `队列题数 ${qcount}（默认买家意图）`);
  const sess = await side.$eval("#session", e => e.value);
  ok(sess === "sandbox", `采样环境默认「一次性沙箱」= ${sess}`);

  console.log("【4】选引擎 + 填入问题（不代发）");
  await side.selectOption("#platSel", "chatgpt");
  await page.bringToFront();                  // 让 lastFocusedWindow 指向被采页面
  await side.waitForTimeout(300);
  await side.click("#fill");
  await side.waitForTimeout(800);
  const boxText = await page.evaluate(() => document.querySelector("#prompt-textarea").textContent);
  const userMsgs = await page.$$eval('[data-message-author-role="user"]', e => e.length);
  ok(boxText.length > 5, `问题已填入输入框：「${boxText.slice(0, 24)}…」`);
  ok(userMsgs === 0, "未自动发送（页面上还没有用户消息）");

  console.log("【5】人工发送 → 等生成 → 提取");
  await page.click('[data-testid="send-button"]');
  await page.waitForTimeout(2500);
  await side.bringToFront(); await page.bringToFront();
  await side.click("#extract");
  await side.waitForTimeout(1500);
  let meta = await side.$eval("#exmeta", e => e.textContent);
  if (!/字/.test(meta)) { await side.waitForTimeout(2500); await side.click("#extract"); await side.waitForTimeout(1200);
    meta = await side.$eval("#exmeta", e => e.textContent); }
  ok(/字/.test(meta), `提取结果：${meta.trim()}`);

  console.log("【6】保存 + 上传入库");
  await side.click("#save");
  await side.waitForTimeout(600);
  const cnt = await side.$eval("#count", e => e.textContent);
  ok(+cnt >= 1, `已采集计数 = ${cnt}（chrome.storage 生效）`);
  await side.click("#upload");
  await side.waitForTimeout(2500);
  const up = await side.$eval("#upmsg", e => e.textContent);
  ok(/已导入/.test(up), `回传结果：${up.trim()}`);

  console.log("【7】看板侧确认");
  const r = await (await fetch(`${DASH}/api/samples/aigclink?limit=5`)).json();
  const mine = (r.rows || []).filter(x => x.sample_mode === "extension");
  ok(mine.length > 0, mine.length
    ? `样本库可见：${mine[0].date} ${mine[0].platform} ${mine[0].question_id} · 环境=${mine[0].session_label} · 等级=${mine[0].evidence_level} · 引用${mine[0].citations}条`
    : "样本库里没有插件样本");

  await ctx.close();
  fs.rmSync(dir, { recursive: true, force: true });
  fs.rmSync(profile, { recursive: true, force: true });
  console.log("\n沙箱与扩展副本已清除");
})().catch(e => { console.error("测试失败：", e.message); process.exit(1); });
