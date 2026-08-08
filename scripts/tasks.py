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

# 风险分级：优先级说「多重要」，风险说「动手时多小心」。二者独立——
# 解封 robots 是 P0 也是高风险（改错一行封掉全站）。执行顺序按「先低风险，
# 高风险单独排期并留回滚」，见 method.md 保护性纪律。
RISK_LABEL = {"low": "低风险快速优化", "watch": "需观察的内容调整", "high": "高风险技术改造"}
# 动 robots / WAF / noindex / 渲染架构：错一处影响全站抓取，必须小批量+可回滚
_HIGH_CHECKS = {"site.no_ai_bot_block", "site.no_ai_ua_block", "pages.static_text", "pages.no_noindex"}
# 纯新增资产，不改已有页面的 URL/标题/正文，随时可撤
_LOW_CHECKS = {"site.has_sitemap", "site.robots_sitemap_declared", "site.has_llms_txt",
               "site.llms_txt_valid", "pages.has_jsonld"}


def risk_of(t: dict) -> str:
    check = (t.get("acceptance") or {}).get("check") or ""
    if check in _HIGH_CHECKS or "部分路径封禁" in t.get("title", ""):
        return "high"
    if check in _LOW_CHECKS:
        return "low"
    # 站外动作（词条/榜单/平台运营）与内部知识库不动自己站点，无既有权重风险
    if t.get("package") in ("外部证据", "知识库"):
        return "low"
    # 其余是改已有页面内容或新建内容：发布后按 7/14/28 天观察窗看数据
    return "watch"


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
    """站点技术层与页面层工单。无自有网站的项目整层不适用，直接返回空。"""
    if audit.get("no_site") or not G.has_site(cfg):
        return []
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
    if site.get("ai_ua_blocked"):
        out.append(_t(next(seq), "P0", "页面技术",
                      "解除 WAF/CDN 对 AI 爬虫的差异封锁",
                      f"普通浏览器 200，但换 {'、'.join(site['ai_ua_blocked'])} 的 UA 抓首页被拒——"
                      "robots 放行没用，引擎侧等于不存在，且站长在浏览器里看不出来",
                      "到 CDN/防火墙（Cloudflare Bot Fight、阿里云 WAF 等）给这些爬虫 UA 加白名单，"
                      "不要用「拦所有 bot」的一刀切规则", "开发", "S",
                      {"type": "auto", "check": "site.no_ai_ua_block",
                       "desc": "重抓时用 AI 爬虫 UA 探测首页不再被拒"}))
    for p in site.get("ai_bots_partial", []) or []:
        out.append(_t(next(seq), "P1", "页面技术",
                      f"核对 robots 对 {p['bot']} 的部分路径封禁",
                      f"{p['count']}/{p['sampled']} 个抽样内容页命中 {p.get('rule') or '封禁规则'}"
                      f"（如 {p['paths'][0]}）。封搜索结果页/带参数页是对的，封内容页是自伤",
                      "逐条核对命中的 Disallow：确认只封低价值路径（站内搜索、会话参数、结账页），"
                      "内容页被误伤的改规则放行", "开发", "S",
                      {"type": "manual",
                       "desc": "封禁是刻意为之（低价值页）而非误伤内容页，需人工确认"}))
    if not site.get("has_sitemap"):
        out.append(_t(next(seq), "P0", "页面技术", "补 sitemap.xml 并提交各搜索引擎",
                      "无 sitemap，收录效率和覆盖面打折（method.md 可抓取性）",
                      "生成 sitemap.xml，robots.txt 里声明，提交百度/必应/Google/夸克",
                      "开发", "S",
                      {"type": "auto", "check": "site.has_sitemap", "desc": "重抓能取到 sitemap.xml"}))
    elif site.get("robots_sitemap_declared") is False:
        out.append(_t(next(seq), "P2", "页面技术", "robots.txt 里声明 Sitemap: 行",
                      "sitemap 存在但 robots 没声明，AI 抓取器发现新页面更慢",
                      "在 robots.txt 末尾加一行 `Sitemap: <完整 URL>`", "开发", "S",
                      {"type": "auto", "check": "site.robots_sitemap_declared",
                       "desc": "robots.txt 含 Sitemap: 声明"}))
    if not site.get("has_llms_txt"):
        out.append(_t(next(seq), "P1", "知识库", "上线 /llms.txt 官方事实索引",
                      "低成本给 AI 一份人工整理的官方索引，国内很多站没做（content-patterns.md 第 7 节）",
                      "用 `geo.py generate --asset llms` 产出后部署到网站根目录", "开发", "S",
                      {"type": "auto", "check": "site.has_llms_txt", "desc": "重抓能取到 /llms.txt"}))
    else:
        lch = site.get("llms_txt_check") or {}
        if lch.get("broken") or lch.get("robots_blocked"):
            bads = [b["url"] for b in lch.get("broken", [])] + \
                   [b["url"] for b in lch.get("robots_blocked", [])]
            out.append(_t(next(seq), "P1", "知识库", "修复 llms.txt 里的失效/被封链接",
                          "llms.txt 只有指向可抓取的有效页面才有意义；指向 404 或被 robots 封禁的页面"
                          "等于递给 AI 一份坏地图",
                          "逐条修复：失效链接改成有效 URL 或删掉；被 robots 封禁的路径解除封禁或换页面",
                          "开发", "S",
                          {"type": "auto", "check": "site.llms_txt_valid",
                           "desc": "llms.txt 抽样链接全部 200 且未被 robots 封禁"},
                          affected=bads[:10]))

    if site.get("sitemap_noisy_urls"):
        out.append(_t(next(seq), "P2", "页面技术", "清理 sitemap 里的低价值 URL",
                      f"sitemap 含 {site['sitemap_noisy_urls']} 条带参数/搜索/翻页 URL"
                      f"（如 {site.get('sitemap_noisy_example')}），会把低质片段灌进检索索引、"
                      "稀释实体表征（method.md 可抓取性）",
                      "sitemap 只保留值得被引用的规范页；低价值路径用 robots 通配符挡掉"
                      "（`Disallow: /*?session=`、`Disallow: /search?`）", "开发", "S",
                      {"type": "auto", "check": "site.sitemap_clean",
                       "desc": "sitemap 里不再有带参数/搜索/翻页 URL"}))

    # 语言覆盖（双市场必查）
    lc = audit.get("language_coverage") or {}
    if lc.get("multilingual") and lc.get("content_pages") \
            and lc.get("hreflang_pages", 0) / lc["content_pages"] < 0.3:
        out.append(_t(next(seq), "P1", "页面技术", "多语言页面补 hreflang 声明",
                      f"多语言站但只有 {lc.get('hreflang_pages', 0)}/{lc['content_pages']} 个内容页"
                      "声明 hreflang，引擎会把各语言版本当重复内容，跨市场检索时挂错语言页面",
                      "每个多语言页面加全套 `<link rel=\"alternate\" hreflang>` 互指（含 x-default），"
                      "与 canonical 保持一致", "开发", "M",
                      {"type": "auto", "check": "site.hreflang_gte:0.5",
                       "desc": "内容页 hreflang 覆盖率 ≥ 50%"}))
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

    noidx = [p["url"] for p in pages
             if _has_issue(p, "NOINDEX", "noindex") or _has_issue(p, "XROBOTS_NOINDEX", "X-Robots-Tag")]
    if noidx:
        t = _t(next(seq), "P0", "页面技术", "移除内容页上的 noindex（meta / X-Robots-Tag）",
               "带 noindex 的页面等于主动退出候选池；X-Robots-Tag 是响应头，源码里看不到，"
               "常常是 CDN 或中间件配置带病上线",
               "逐页确认 noindex 是否刻意；不是的话删掉 meta robots noindex，"
               "并检查 CDN/网关有没有全局注入 X-Robots-Tag 头",
               "开发", "S", {"type": "auto", "check": "pages.no_noindex",
                             "desc": "受影响页面重抓后不再带 noindex"},
               affected=noidx)
        t["baseline_count"] = len(noidx)
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

    # 段落级可引：检索按段落选材，整页没有一段能独立引用 = 页面再长也选不中
    noquote = [p["url"] for p in pages if _has_issue(p, "NO_QUOTABLE_PASSAGE", "可独立引用的段落")]
    if len(noquote) >= 2:
        t = _t(next(seq), "P1", "内容矩阵", "核心页改出可独立引用的证据段",
               f"{len(noquote)} 页正文不短但没有一段自包含可引——每段要么太短、要么没有数字/定义/"
               "步骤等硬信息。检索的最小单元是段落，不是页面（method.md 段落级可引）",
               "每页挑 2–3 个核心 H2 小节改成证据段：60 词以上、含具体数字或定义句或操作步骤，"
               "段落开头直接回答小节标题的问题",
               "内容", "M", {"type": "auto", "check": "pages.quotable",
                             "desc": "受影响页面「无可引段落」数下降 ≥ 50%"},
               affected=noquote[:30])
        t["baseline_count"] = len(noquote)
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
        _t(next(seq), "P1", "监测闭环", "接入 AI 流量归因（渠道组 + 日志 + 来源快照）",
           "只测「被引用」不测「带来转化」，监测就是汇报表演；AI 来源会话是可见性投入的业务对账单"
           "（references/attribution.md）",
           "用 `geo.py generate --asset attribution` 产出配置包：GA4 建「AI 引擎」渠道组、"
           "服务器日志跑统计脚本、转化事件保存来源快照。报告口径写「可归因 ≥ N」，不外推",
           "开发", "S", {"type": "manual", "desc": "渠道组已建、日志脚本可跑、转化事件带来源快照（人工确认）"}),
    ]


# ---------------------------------------------------------------- 主流程

def build(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json")
    if not audit:
        if G.has_site(cfg):
            G.die("缺 audit.json，先运行 audit")
        audit = {"site": {}, "pages": [], "block_gap": [], "no_site": True}

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
        t["risk"] = risk_of(t)

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
