"""页面 GEO 体检：把 citation-lab 的实证结论变成可计算的分数。

评分口径全部来自 references/method.md 里记录的实测数字，不是拍脑袋：
  长度   Top 四分位页面 1,943 词 / Bottom 四分位 170 词（11.4x）
  结构   Top 四分位 10.59 个标题、47.49 个段落、列表密度 0.428
  抽取块 含数字 +61.6%、含定义 +57.3%、含对比 +55.3%、含 how-to +41.2%
  对题性 llm_relevance_score 是影响力最强预测因子（r = 0.432）

产物：work/<slug>/audit.json
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

import geolib as G

# ------------------------------------------------------------ 抽取块识别

# 三语站点三语判：只认中英表述会把日文页整体误判成「缺块」
RE_DEFINITION = re.compile(
    r"(是一[款种个家类]|是指|指的是|定义为|全称[为是]|又称|简称为?|属于一[种类]"
    r"|とは|を指す|と呼ばれ|の略"
    r"|\bis an? \w+|\brefers to\b|\bis defined as\b|\bstands for\b)", re.I
)
RE_NUMBER = re.compile(
    r"\d[\d,\.]*\s*(%|％|万|亿|千|倍|元|美元|人|家|个|天|小时|分钟|秒|次|条|款|年|月|"
    r"件|社|名|回|億|円|時間|"
    r"percent|x\b|hours?|days?|users?|customers?)"
)
RE_COMPARE = re.compile(r"(对比|相比|区别|差异|优于|不如|竞品|替代|选型|哪个好|比較|違い|\bvs\.?\b|\bversus\b|\balternatives?\b)", re.I)
RE_HOWTO = re.compile(r"(第[一二三四五六七八九十\d]+步|步骤\s*[一二三四五六七八九十\d]|操作流程|手順|ステップ\s*\d|使い方|\bstep\s*\d|\bhow to\b)", re.I)
# 「如何/怎么」只是弱信号，必须与列表结构共现才算操作步骤块（否则问句标题就送分）
RE_HOWTO_SOFT = re.compile(r"(如何|怎么)")
# 登录/注册/购物车/联系页等功能页天然低内容，不按 SPA 空壳 P0 误报
FUNC_PAGE = re.compile(r"/(login|signin|signup|register|cart|checkout|account|auth|contact)(/|$)", re.I)
RE_FAQ = re.compile(r"(常见问题|常见疑问|问答|よくある質問|\bFAQ\b|^\s*[问Q][:：]|答[:：])", re.I | re.M)
RE_DATE = re.compile(r"(20\d{2}[-/年]\s?\d{1,2}[-/月]\s?\d{1,2}|更新[于时间]*[:：]?\s*20\d{2}|最后更新|发布于|\bupdated\b|\bpublished\b)", re.I)
RE_AUTHOR = re.compile(r"(作者|撰文|编辑[:：]|著者|執筆|\bauthor\b|\bby\s+[A-Z][a-z]+)", re.I)

AUTHORITY_SCHEMA = {
    "Organization", "Corporation", "Product", "SoftwareApplication", "Service",
    "FAQPage", "Article", "TechArticle", "NewsArticle", "BlogPosting",
    "HowTo", "BreadcrumbList", "WebSite", "Review", "AggregateRating", "Offer",
}


def band(value: float, stops: list[tuple[float, float]]) -> float:
    """stops 为 [(阈值, 得分比例)]，从高到低取第一个满足的。"""
    for threshold, ratio in stops:
        if value >= threshold:
            return ratio
    return 0.0


def jsonld_has_key(obj, keys: set[str]) -> bool:
    """递归查 JSON-LD 原始 dict 的键（dateModified 是属性不是 @type，查 types 恒查不到）。"""
    if isinstance(obj, dict):
        return any(k in keys or jsonld_has_key(v, keys) for k, v in obj.items())
    if isinstance(obj, list):
        return any(jsonld_has_key(x, keys) for x in obj)
    return False


def score_page(page: dict, keywords: list[str]) -> dict:
    text = page.get("text", "") or ""
    wc = page.get("word_count", 0)
    h1, h2 = page.get("h1", []), page.get("h2", [])
    paras = page.get("para_count", 0)
    lis = page.get("li_count", 0)
    types = set(page.get("jsonld_types", []))

    issues: list[str] = []
    issue_codes: list[str] = []

    def issue(code: str, msg: str):
        issue_codes.append(code)
        issues.append(msg)

    d: dict[str, float] = {}

    # 1. 可抓取性 15
    s = 0.0
    status = page.get("status") or 0
    if status == 200:
        s += 7
    elif 200 < status < 400:
        s += 3
        issue("NON_200_STATUS", "P1 页面返回非 200（如 202/3xx），部分抓取器会直接放弃")
    else:
        issue("PAGE_UNREACHABLE", "P0 页面不可访问，AI 抓取器同样拿不到")
    if "noindex" not in (page.get("meta_robots") or "").lower():
        s += 3
    else:
        issue("NOINDEX", "P0 meta robots 含 noindex，等于主动退出候选池")
    if page.get("canonical"):
        s += 2
    else:
        issue("NO_CANONICAL", "P2 缺 canonical，重复内容会稀释信号")
    if wc >= 120:
        s += 3
    elif FUNC_PAGE.search(urlparse(page.get("url") or "").path):
        issue("LOW_CONTENT_PAGE", "P2 低内容功能页（登录/注册/购物车等），内容少属正常，可考虑补充说明性文案")
    else:
        issue("SPA_SHELL", "P0 静态 HTML 里几乎没有正文（疑似纯前端渲染），AI 抓取器读不到内容")
    d["可抓取性"] = s

    # 2. 内容长度 15（1000+ 词是进入高影响力区间的门槛）
    r = band(wc, [(1500, 1.0), (1000, 0.85), (600, 0.6), (300, 0.35), (120, 0.15)])
    d["内容长度"] = 15 * r
    if wc < 1000:
        issue("SHORT_CONTENT", "P1 正文不足 1000 词门槛（高影响力页面平均 1,943 词，Bottom 四分位仅 170 词）")

    # 3. 结构规范 20
    s = 0.0
    if len(h1) == 1:
        s += 4
    else:
        issue("BAD_H1", "P1 H1 不是唯一一个（0 个或多个），主题信号混乱")
    s += 6 * band(len(h2), [(8, 1.0), (6, 0.85), (4, 0.6), (2, 0.3)])
    if len(h2) < 6:
        issue("FEW_H2", "P1 H2 小节不足 6 个，高影响力页面平均 10.59 个标题；建议拆到 6-10 节")
    s += 5 * band(paras, [(40, 1.0), (25, 0.8), (15, 0.55), (8, 0.3)])
    density = lis / max(paras + lis, 1)
    s += 5 * band(density, [(0.35, 1.0), (0.2, 0.75), (0.1, 0.45), (0.03, 0.2)])
    if density < 0.1:
        issue("LOW_LIST_DENSITY", "P1 列表密度过低，Top 四分位页面为 0.428；把要点改成 ul/ol 更易被抽取")
    d["结构规范"] = s

    # 4. 可抽取块 25（GEO 的核心杠杆）
    has = {
        "定义": bool(RE_DEFINITION.search(text)),
        "数字事实": len(RE_NUMBER.findall(text)) >= 3,
        "对比": bool(RE_COMPARE.search(text)) or page.get("table_count", 0) >= 1,
        "操作步骤": bool(RE_HOWTO.search(text)) or (bool(RE_HOWTO_SOFT.search(text)) and lis >= 3),
        "FAQ": bool(RE_FAQ.search(text)) or "FAQPage" in types,
    }
    block_codes = {"定义": "NO_DEFINITION", "数字事实": "NO_NUMBERS", "对比": "NO_COMPARISON",
                   "操作步骤": "NO_HOWTO", "FAQ": "NO_FAQ"}
    weights = {"定义": 6, "数字事实": 6, "对比": 5, "操作步骤": 5, "FAQ": 3}
    d["可抽取块"] = sum(w for k, w in weights.items() if has[k])
    for k, ok in has.items():
        if not ok:
            issue(block_codes[k], f"P1 缺「{k}」块，补上可显著提升被吸收概率")

    # 5. 权威信号 15
    s = 0.0
    if RE_DATE.search(text) or jsonld_has_key(page.get("jsonld_raw"), {"dateModified", "datePublished"}):
        s += 4
    else:
        issue("NO_DATE", "P1 正文没有可见的发布/更新日期，时效性无法判断")
    if RE_AUTHOR.search(text):
        s += 2
    ext = page.get("external_links", 0)
    s += 4 * band(ext, [(6, 1.0), (3, 0.7), (1, 0.4)])
    if ext < 3:
        issue("FEW_EXTERNAL_LINKS", "P2 几乎不引用外部来源，证据链偏弱")
    hit_schema = types & AUTHORITY_SCHEMA
    s += 5 * band(len(hit_schema), [(3, 1.0), (2, 0.75), (1, 0.45)])
    if not hit_schema:
        issue("NO_JSONLD", "P0 没有任何结构化数据（JSON-LD），机器读不懂这页在讲什么实体")
    d["权威信号"] = s

    # 6. 对题性 10（title / h1 / h2 是否覆盖目标问题里的词）
    surface = " ".join([page.get("title", "")] + h1 + h2).lower()
    hits = [k for k in keywords if k and k.lower() in surface]
    cover = len(hits) / max(len(keywords), 1) if keywords else 0
    d["对题性"] = 10 * band(cover, [(0.4, 1.0), (0.25, 0.8), (0.12, 0.55), (0.04, 0.3)])
    if cover < 0.12:
        issue("LOW_RELEVANCE", "P1 标题体系几乎不含目标问题关键词，对题性是影响力最强的预测因子（r=0.432）")

    total = round(sum(d.values()), 1)
    return {
        "url": page.get("url"),
        "title": page.get("title", "")[:120],
        "word_count": wc,
        "score": total,
        "grade": "A" if total >= 80 else "B" if total >= 65 else "C" if total >= 45 else "D",
        "dimensions": {k: round(v, 1) for k, v in d.items()},
        "blocks": has,
        "jsonld_types": sorted(types),
        "issues": issues,
        "issue_codes": issue_codes,
    }


def keywords_from_config(cfg: dict) -> list[str]:
    b = cfg.get("brand", {})
    # 品牌词不算对题性证据：标题里出现自家品牌名天经地义，用它撑覆盖率是自我安慰
    brand_terms = set()
    for k in [b.get("name")] + list(b.get("aliases", []) or []) + list(b.get("products", []) or []):
        if k:
            brand_terms.add(str(k).lower())
    kws = set()
    for q in cfg.get("questions", []):
        for token in re.findall(r"[一-鿿A-Za-z]{2,}", q.get("text", "")):
            if len(token) >= 2:
                kws.add(token)
    # 只保留最有区分度的一批，避免「的」「怎么」这种噪声撑高覆盖率
    stop = {"什么", "怎么", "哪个", "如何", "可以", "适合", "推荐", "有没有", "the", "and", "for", "how", "what", "which"}
    return sorted({k for k in kws if k.lower() not in stop and k.lower() not in brand_terms
                   and len(k) >= 2})[:40]


def run(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    pages = G.read_jsonl(pdir / "evidence" / "pages.jsonl")
    if not pages:
        G.die("没有抓取结果，先运行：python3 scripts/geo.py crawl --slug " + slug)
    site = G.read_json(pdir / "evidence" / "site.json", {})
    kws = keywords_from_config(cfg)

    results = [score_page(p, kws) for p in pages]
    # 均分分母只计能打开的页（含 0 分页）：和 grade_distribution 同口径，
    # 抓不到的页本来就不该参与内容质量均分
    ok = [r for r, p in zip(results, pages) if (p.get("status") or 0) == 200]
    avg = round(sum(r["score"] for r in ok) / max(len(ok), 1), 1)

    # 语言覆盖：做双市场时，「有没有英文原生内容」是海外 GEO 的门票
    market = cfg.get("market", "cn")
    lang_dist: dict[str, int] = {}
    for p in pages:
        if p.get("word_count", 0) >= 120:
            # 有正文就从正文重算语言，不盲信存储字段——evidence 可能是旧版口径抓的
            if p.get("text"):
                lang = G.page_language(p["text"], p.get("lang", ""))
            else:
                lang = p.get("language", "unknown")
            lang_dist[lang] = lang_dist.get(lang, 0) + 1
    # mixed 单列，不双计进 zh/en——双计会让「中英对等」判断失真
    en_pages = lang_dist.get("en", 0)
    zh_pages = lang_dist.get("zh", 0)
    ja_pages = lang_dist.get("ja", 0)

    # 站点级问题
    site_issues = []
    if market in ("global", "both") and en_pages == 0:
        site_issues.append(
            "P0 抓到的页面里没有一页是英文原生内容，海外 AI 引用的可识别语言中英文占 82.90%–95.07%，"
            "翻译腔或中文页几乎进不了候选池")
    if market in ("cn", "both") and zh_pages == 0:
        site_issues.append("P0 抓到的页面里没有中文内容，国内平台无从引用")
    if market == "both" and en_pages and zh_pages and abs(en_pages - zh_pages) > max(en_pages, zh_pages) * 0.7:
        thin = "英文" if en_pages < zh_pages else "中文"
        site_issues.append(f"P1 中英内容严重不对等（中文 {zh_pages} 页 / 英文 {en_pages} 页），{thin}侧是明显短板")
    if site.get("ai_bots_blocked"):
        site_issues.append("P0 robots.txt 封禁了 " + "、".join(site["ai_bots_blocked"]) + "，这些引擎永远抓不到你")
    if not site.get("has_sitemap"):
        site_issues.append("P0 没有 sitemap.xml，收录效率和覆盖面都会打折")
    if not site.get("has_llms_txt"):
        site_issues.append("P2 没有 /llms.txt，可以低成本给 AI 一份官方事实索引")
    grade_dist = {g: sum(1 for r in results if r["grade"] == g) for g in "ABCD"}

    # 全站最常见的缺口 → 直接就是 P0 内容工程清单
    gap = {}
    for r in results:
        for k, v in r["blocks"].items():
            gap.setdefault(k, 0)
            gap[k] += 0 if v else 1
    block_gap = sorted(gap.items(), key=lambda x: -x[1])

    out = {
        "slug": slug,
        "audited_at": G.now_iso(),
        "market": market,
        "site": site,
        "language_coverage": {"distribution": lang_dist, "zh_pages": zh_pages,
                              "en_pages": en_pages, "ja_pages": ja_pages},
        "site_issues": site_issues,
        "keywords_used": kws,
        "page_count": len(results),
        "avg_score": avg,
        "grade_distribution": grade_dist,
        "block_gap": [{"block": k, "missing_pages": v, "total": len(results)} for k, v in block_gap],
        "pages": sorted(results, key=lambda r: r["score"]),
    }
    G.write_json(pdir / "audit.json", out)
    G.info(f"体检完成：{len(results)} 页，均分 {avg}，分布 {grade_dist} → {pdir/'audit.json'}")
    return out


if __name__ == "__main__":
    import sys

    run(sys.argv[1])
