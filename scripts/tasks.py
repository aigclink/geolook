"""工单系统：把诊断结果变成可分派、可验收、可追踪的执行任务。

这是执行层的骨架。`tasks.json` 是项目执行状态的**单一真相源**：
  plan      → 从 audit + metrics + benchmark 生成工单
  generate  → 按工单产出资产，回写 asset 路径
  verify    → 重抓后自动判定 acceptance，回写 status

每条工单都必须有：依据（追到 method.md 的哪一条）、负责角色、验收标准、市场。
没有验收标准的不叫工单，叫愿望。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import geolib as G

PACKAGES = ["实体消歧", "页面技术", "内容矩阵", "标题体系", "知识库", "外部证据", "监测闭环"]
OWNERS = ["开发", "内容", "市场", "GEO顾问", "法务", "设计"]
EFFORT = {"S": "≤0.5 人日", "M": "1–3 人日", "L": "≥5 人日"}


def _t(tid, priority, package, title, why, action, owner, effort, acceptance,
       market="both", affected=None, window="30天", assets=None):
    return {
        "id": tid, "priority": priority, "package": package, "market": market,
        "title": title, "why": why, "action": action,
        "owner": owner, "effort": effort, "window": window,
        "affected": affected or [], "acceptance": acceptance,
        "status": "todo", "assets": assets or [], "evidence": [], "closed_at": None,
    }


# ---------------------------------------------------------------- 生成规则

def _has_issue(page: dict, code: str, text_fallback: str) -> bool:
    """优先按 issue_codes 结构化匹配；旧 audit.json 没有该字段时退回文案子串。"""
    codes = page.get("issue_codes")
    if codes is not None:
        return code in codes
    return any(text_fallback in i for i in page.get("issues", []))


def from_audit(audit: dict, cfg: dict, seq) -> list[dict]:
    """站点技术层与页面层工单。"""
    out = []
    site = audit.get("site", {})
    market = cfg.get("market", "cn")
    pages = audit.get("pages", [])
    weak = [p["url"] for p in pages if p["score"] < 65]

    # —— 站点级 ——
    if site.get("ai_bots_blocked"):
        out.append(_t(next(seq), "P0", "页面技术",
                      "解除 robots.txt 对 AI 抓取器的封禁",
                      f"robots 封禁 {'、'.join(site['ai_bots_blocked'])}，这些引擎永远抓不到你（method.md 可抓取性）",
                      "移除对应 Disallow，或改为仅屏蔽后台路径", "开发", "S",
                      {"type": "auto", "check": "site.no_ai_bot_block",
                       "desc": "重抓后 robots 不再整站封禁任何 AI 抓取器"}))
    if not site.get("has_sitemap"):
        out.append(_t(next(seq), "P0", "页面技术", "补 sitemap.xml 并提交各搜索引擎",
                      "无 sitemap，收录效率和覆盖面打折（method.md 可抓取性）",
                      "生成 sitemap.xml，robots.txt 里声明，提交百度/必应/Google/夸克",
                      "开发", "S",
                      {"type": "auto", "check": "site.has_sitemap", "desc": "重抓能取到 sitemap.xml"}))
    if not site.get("has_llms_txt"):
        out.append(_t(next(seq), "P1", "知识库", "上线 /llms.txt 官方事实索引",
                      "低成本给 AI 一份人工整理的官方索引，国内很多站没做（content-patterns.md 第 7 节）",
                      "用 `geo.py generate --asset llms` 产出后部署到网站根目录", "开发", "S",
                      {"type": "auto", "check": "site.has_llms_txt", "desc": "重抓能取到 /llms.txt"}))

    # 语言覆盖（双市场必查）
    lc = audit.get("language_coverage") or {}
    if market in ("global", "both") and lc.get("en_pages", 0) == 0:
        out.append(_t(next(seq), "P0", "内容矩阵", "建英文原生内容区",
                      "海外 AI 引用的可识别语言里英文占 82.90%–95.07%，机翻页进不了候选池（global-platforms.md）",
                      "至少 8 个英文原生页面：首页、产品、定价、对比、FAQ、案例 ×3。不是翻译中文页",
                      "内容", "L", {"type": "auto", "check": "site.en_pages_gte:8",
                                    "desc": "英文有效内容页 ≥ 8"}, market="global"))
    elif market == "both" and lc.get("en_pages", 0) and lc.get("zh_pages", 0):
        en, zh = lc["en_pages"], lc["zh_pages"]
        if abs(en - zh) > max(en, zh) * 0.7:
            thin = "英文" if en < zh else "中文"
            out.append(_t(next(seq), "P1", "内容矩阵", f"补齐{thin}侧内容，中英对等",
                          f"中文 {zh} 页 / 英文 {en} 页严重不对等，{thin}侧是短板",
                          f"把{thin}侧页面数补到与另一侧相差 30% 以内", "内容", "L",
                          {"type": "auto", "check": f"site.lang_balance:0.7",
                           "desc": "中英页面数差距 ≤ 70%"}))

    # —— 页面级：按缺口类型聚合成一条工单，而不是一页一条 ——
    spa = [p["url"] for p in pages if _has_issue(p, "SPA_SHELL", "静态 HTML 里几乎没有正文")]
    if spa:
        t = _t(next(seq), "P0", "页面技术", "修复前端渲染空壳页（SSR / 预渲染）",
               "静态 HTML 无正文，多数 AI 抓取器看到的是空白页——国内官网最常见致命伤（method.md 可抓取性）",
               "对受影响路由启用 SSR 或预渲染，确保 curl 拿到的 HTML 含完整正文",
               "开发", "M", {"type": "auto", "check": "pages.static_text",
                             "desc": "受影响页面重抓后正文词数 ≥ 120"},
               affected=spa)
        t["baseline_count"] = len(spa)
        out.append(t)

    no_schema = [p["url"] for p in pages if not p.get("jsonld_types")]
    if no_schema:
        t = _t(next(seq), "P0", "页面技术", "全站补 JSON-LD 结构化数据",
               "无结构化数据，机器读不懂这页在讲什么实体（method.md 权威信号）",
               "用 `geo.py generate --asset jsonld` 产出补丁，按页面类型挂 "
               "Organization / SoftwareApplication / Article / FAQPage / BreadcrumbList",
               "开发", "M", {"type": "auto", "check": "pages.has_jsonld",
                             "desc": "受影响页面重抓后含 JSON-LD"},
               affected=no_schema)
        t["baseline_count"] = len(no_schema)
        out.append(t)

    # 抽取块缺口 → 每种一条，附实测增益
    gain = {"数字事实": "+61.6%", "定义": "+57.3%", "对比": "+55.3%", "操作步骤": "+41.2%",
            "FAQ": "利于问答召回（格式本身无增益）"}
    for g in audit.get("block_gap", []):
        if g["missing_pages"] >= max(3, g["total"] * 0.3):
            blk = g["block"]
            miss = [p["url"] for p in pages if not p["blocks"].get(blk)]
            t = _t(next(seq), "P1", "内容矩阵", f"全站补「{blk}」抽取块",
                   f"{g['missing_pages']}/{g['total']} 页缺失；实测影响力增益 {gain.get(blk, '—')}（method.md 可抽取块）",
                   f"参照 content-patterns.md，在核心页补{blk}块；定义句需与事实卡逐字一致",
                   "内容", "M", {"type": "auto", "check": f"pages.block:{blk}",
                                 "desc": f"缺「{blk}」的页面数下降 ≥ 50%"},
                   affected=miss[:30])
            # affected 截断到 30 条只是展示用，验收基线必须是真实缺口数
            t["baseline_count"] = len(miss)
            out.append(t)

    short = [p["url"] for p in pages if p["word_count"] < 1000 and p["word_count"] >= 100]
    if len(short) >= 3:
        t = _t(next(seq), "P1", "内容矩阵", "核心页正文扩到 1000+ 词",
               "高影响力页面平均 1,943 词，Bottom 四分位仅 170 词（method.md 内容长度）",
               "优先扩产品页、案例页、对比页；加定义、数字表、步骤、边界说明，不是灌水",
               "内容", "L", {"type": "auto", "check": "pages.wordcount_gte:1000",
                             "desc": "正文 <1000 词的页面数下降 ≥ 40%"},
               affected=short[:30])
        t["baseline_count"] = len(short)
        out.append(t)

    thin_h2 = [p["url"] for p in pages if len(p.get("dimensions", {})) and p["score"] < 70]
    if audit.get("avg_score", 0) < 70:
        out.append(_t(next(seq), "P1", "页面技术", f"站点均分从 {audit.get('avg_score')} 提到 70",
                      "均分低于 70 说明整体处于「需要改造」区间（method.md 评分口径）",
                      "按 audit.json 里分数最低的 10 页逐页改：H1 唯一、H2 拆到 6–10 节、列表密度 ≥0.35、加更新日期",
                      "内容", "L", {"type": "auto", "check": "site.avg_score_gte:70",
                                    "desc": "重跑 audit 均分 ≥ 70"},
                      affected=thin_h2[:10]))
    return out


def from_metrics(metrics: dict, cfg: dict, seq) -> list[dict]:
    """AI 答案可见性层工单，按市场分开。"""
    out = []
    if not metrics or not metrics.get("platforms"):
        return out
    for mk, mk_name in (("cn", "国内"), ("global", "海外")):
        rows = {p: m for p, m in metrics["platforms"].items() if m.get("market", "cn") == mk}
        if not rows:
            continue
        # mention_rate / own_domain_cite_rate 为 None = 该平台只采了点名题（未测），
        # 不参与平均；全 None 时该指标「未测」，不下结论工单，不编数。
        rates = [m["mention_rate"] for m in rows.values() if m.get("mention_rate") is not None]
        target = cfg.get("targets", {}).get("mention_rate", 0.3)
        if rates:
            avg = sum(rates) / len(rates)
            if avg < target:
                out.append(_t(next(seq), "P1", "监测闭环",
                              f"{mk_name}无提示提及率 {avg:.0%} → {target:.0%}",
                              f"{mk_name}市场 {len(rates)} 个已测平台的无提示提及率均值仅 {avg:.0%}，"
                              "说明还没进入候选集（method.md 三段漏斗 ①②）",
                              "这是内容矩阵 + 外部信源两个包的综合结果指标，不单独派工，用于季度验收",
                              "GEO顾问", "L",
                              {"type": "auto", "check": f"metrics.mention_rate_gte:{mk}:{target}",
                               "desc": f"{mk_name}平均无提示提及率 ≥ {target:.0%}"}, market=mk))
        own = [m["own_domain_cite_rate"] for m in rows.values() if m.get("own_domain_cite_rate") is not None]
        if own and sum(own) / len(own) < 0.1:
            out.append(_t(next(seq), "P1", "外部证据",
                          f"{mk_name}让官网进得了 AI 的检索结果",
                          f"{mk_name}引用官网率 {sum(own)/len(own):.0%}。官网内容再对，检索不到等于不存在",
                          "提交各引擎收录；在高频被引域名上发带官网链接的内容；"
                          "母品牌/关联站挂子产品入口", "市场", "M",
                          {"type": "auto", "check": f"metrics.own_cite_gte:{mk}:0.1",
                           "desc": f"{mk_name}引用官网率 ≥ 10%"}, market=mk))
        # 品牌认知错误 → P0
        for plat, m in rows.items():
            pr = m.get("probe") or {}
            if pr.get("samples") and (pr.get("own_domain_cite_rate") or 0) == 0:
                continue
    return out


def from_benchmark(bench: dict, cfg: dict, seq) -> list[dict]:
    """外部信源层工单——依据 CN-GEO 实测榜，不靠主观印象。"""
    out = []
    if not bench:
        return out
    missing = bench.get("cross_platform_missing", [])
    rank = [m for m in missing if "榜单" in m["category"]]
    if rank:
        out.append(_t(next(seq), "P1", "外部证据", "拿下榜单/品牌库站词条",
                      "仅 28 个榜单站域名占全库引用 9.1%，且引用位置全库最靠前；"
                      "AI 回答「有哪些/哪个好/怎么选」时最省事就是抄现成榜单（cn-source-ranking.md）",
                      "提交词条：" + "、".join(f"`{m['domain']}`" for m in rank),
                      "市场", "M",
                      {"type": "auto", "check": "external.any:" + ",".join(m["domain"] for m in rank),
                       "desc": "采样中出现任一榜单站引用"}, market="cn"))
    plat = [m for m in missing if m["category"] == "内容平台"]
    if plat:
        out.append(_t(next(seq), "P1", "外部证据", "进内容平台生态",
                      "内容平台四家占全库引用 16.4%；qq.com 是元宝 20.5% 的来源，"
                      "toutiao.com 是豆包系入口（cn-source-ranking.md）",
                      "开设并持续运营：" + "、".join(f"`{m['domain']}`" for m in plat),
                      "内容", "L",
                      {"type": "auto", "check": "external.any:" + ",".join(m["domain"] for m in plat),
                       "desc": "采样中出现任一内容平台引用"}, market="cn"))
    for gap in bench.get("ecosystem_gaps", []):
        out.append(_t(next(seq), "P2", "外部证据", f"跨过平台生态门槛：{gap['domain']}",
                      f"{gap['why']}——不进这个站，对应平台基本进不去（cn-source-ranking.md 第三节）",
                      f"在 `{gap['domain']}` 建立内容存在（收录/账号/词条）", "市场", "M",
                      {"type": "auto", "check": f"external.any:{gap['domain']}",
                       "desc": f"采样中出现 {gap['domain']} 引用"}, market="cn"))
    return out


def entity_tasks(cfg: dict, seq) -> list[dict]:
    """实体消歧与事实底座——永远存在的基础包。"""
    b = cfg["brand"]
    return [
        _t(next(seq), "P0", "实体消歧", "统一一句话定义，四处逐字一致",
           "口径不一致是 AI 描述品牌漂移的头号原因（content-patterns.md 第 6 节）",
           f"把「{b['name']}」的定义句同步到：首页首屏、关于页、JSON-LD description、llms.txt。逐字相同",
           "内容", "S", {"type": "manual", "desc": "四处定义句文本完全一致（人工核对）"}),
        _t(next(seq), "P0", "知识库", "建品牌事实卡并标注证据等级",
           "所有内容生产的事实底座；无来源的事实一律标待确认（method.md 采样纪律）",
           "填 content/facts.md：实体、别名、产品、关键数字、适用与不适用、禁用表达；每条标 A–E",
           "GEO顾问", "M", {"type": "manual", "desc": "facts.md 存在且每条事实有证据等级"}),
        _t(next(seq), "P1", "知识库", "百科词条（实体消歧地基）",
           "百科是品牌实体消歧的地基；baidu.com 同时是百度AI 37.7%、文心 29.0% 的引用来源",
           "提交百度百科；海外市场同步争取 Wikipedia（需第三方来源支撑）", "市场", "M",
           {"type": "manual", "desc": "词条通过审核并上线"}),
    ]


# ---------------------------------------------------------------- 主流程

def build(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json")
    if not audit:
        G.die("缺 audit.json，先运行 audit")

    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], None) if files else None

    bench = None
    if metrics:
        import benchmark
        doms: dict[str, int] = {}
        for m in metrics["platforms"].values():
            if m.get("market", "cn") == "cn":
                for k, v in m.get("top_cited_domains", {}).items():
                    doms[k] = doms.get(k, 0) + v
        if doms:
            bench = benchmark.compare(doms)

    counter = iter(f"T-{i:03d}" for i in range(1, 999))
    tasks = (entity_tasks(cfg, counter) + from_audit(audit, cfg, counter)
             + from_metrics(metrics, cfg, counter) + from_benchmark(bench, cfg, counter))

    # 排期窗口：P0 → 30 天，P1 → 60 天，P2 → 90 天
    win = {"P0": "30天", "P1": "60天", "P2": "90天"}
    for t in tasks:
        t["window"] = win.get(t["priority"], "90天")

    # 保留已有工单的状态与证据（重跑 plan 不该清空进度）
    old = {t["id"]: t for t in (G.read_json(pdir / "tasks.json", {}) or {}).get("tasks", [])}
    old_by_title = {t["title"]: t for t in old.values()}
    for t in tasks:
        prev = old.get(t["id"]) if old.get(t["id"], {}).get("title") == t["title"] else old_by_title.get(t["title"])
        if prev:
            t.update({"status": prev.get("status", "todo"), "evidence": prev.get("evidence", []),
                      "assets": prev.get("assets", []), "closed_at": prev.get("closed_at")})

    data = {
        "slug": slug, "generated_at": G.now_iso(), "market": cfg.get("market", "cn"),
        "baseline": {"avg_score": audit.get("avg_score"), "pages": audit.get("page_count"),
                     "metrics_date": metrics.get("date") if metrics else None},
        "summary": summarize(tasks),
        "tasks": tasks,
    }
    G.write_json(pdir / "tasks.json", data)
    G.info(f"生成 {len(tasks)} 条工单 → {pdir/'tasks.json'}")
    return data


def summarize(tasks: list[dict]) -> dict:
    def cnt(**kw):
        return sum(1 for t in tasks if all(t.get(k) == v for k, v in kw.items()))
    return {
        "total": len(tasks),
        "by_priority": {p: cnt(priority=p) for p in ("P0", "P1", "P2")},
        "by_status": {s: cnt(status=s) for s in ("todo", "doing", "done", "blocked", "wontfix")},
        "by_package": {p: sum(1 for t in tasks if t["package"] == p) for p in PACKAGES
                       if any(t["package"] == p for t in tasks)},
        "by_market": {m: sum(1 for t in tasks if t["market"] == m) for m in ("cn", "global", "both")},
        "auto_verifiable": sum(1 for t in tasks if t["acceptance"]["type"] == "auto"),
    }


def load(slug: str) -> dict:
    return G.read_json(G.project_dir(slug) / "tasks.json", {"tasks": []})


def save(slug: str, data: dict):
    """写前先备份到 .geo.bak/（保留最近 10 份），写入走原子写。
    tasks.json 是执行状态单一真相源，被误覆盖的代价远大于留几个备份文件。"""
    data["summary"] = summarize(data.get("tasks", []))
    p = G.project_dir(slug) / "tasks.json"
    if p.exists():
        bak = p.parent / ".geo.bak"
        bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        (bak / f"tasks-{stamp}.json").write_text(p.read_text("utf-8"), "utf-8")
        old = sorted(bak.glob("tasks-*.json"))
        for f in old[:-10]:
            f.unlink()
    G.write_json(p, data)


def set_status(slug: str, task_id: str, status: str, note: str = "") -> dict:
    with G.project_lock(slug):
        data = load(slug)
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["status"] = status
                if note:
                    t["evidence"].append({"at": G.now_iso(), "note": note})
                if status == "done":
                    t["closed_at"] = G.now_iso()
                save(slug, data)
                G.info(f"{task_id} → {status}")
                return t
    raise KeyError(f"工单 {task_id} 不存在")
