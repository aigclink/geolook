"""抓取目标站点：站点级信号（robots / sitemap / llms.txt）+ 代表性页面正文。

产物：
  work/<slug>/evidence/site.json      站点级检查结果
  work/<slug>/evidence/pages.jsonl    每页一条（含正文、结构统计、JSON-LD）
  work/<slug>/evidence/html/<n>.html  原始 HTML 快照（供人工复核）
"""

from __future__ import annotations

import re
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

import geolib as G

# 中文站常见的高价值路径关键词 → 优先抓
PRIORITY = [
    "product", "pricing", "price", "solution", "case", "customer", "doc", "docs",
    "help", "faq", "about", "news", "blog", "guide", "compare", "vs", "feature",
    "产品", "价格", "方案", "案例", "客户", "文档", "帮助", "关于", "新闻", "博客",
]


def discover_sitemap(root: str, limit: int = 300) -> list[str]:
    urls: list[str] = []
    seen_maps = set()
    queue = [G.normalize_url(root, "/sitemap.xml"), G.normalize_url(root, "/sitemap_index.xml")]

    robots = G.fetch_text(G.normalize_url(root, "/robots.txt"))
    for m in re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots):
        queue.append(m.strip())

    # 最多只跟 8 个 sitemap 文件：有些站的 sitemap index 挂着上百个分片，会把抓取拖死
    while queue and len(urls) < limit and len(seen_maps) < 8:
        sm = queue.pop(0)
        if not sm or sm in seen_maps:
            continue
        seen_maps.add(sm)
        xml = G.fetch_text(sm)
        if not xml:
            continue
        locs = re.findall(r"<loc>\s*([^<]+?)\s*</loc>", xml)
        if "<sitemapindex" in xml:
            queue.extend(locs[:20])
        else:
            urls.extend(locs)
    return urls


def discover_links(root: str, html: str, limit: int = 200) -> list[str]:
    soup = G.parse_html(html)
    out: list[str] = []
    for a in soup.find_all("a", href=True):
        u = G.normalize_url(root, a["href"])
        if u and G.same_site(root, u) and u not in out:
            out.append(u)
        if len(out) >= limit:
            break
    return out


def rank(urls: list[str], root: str) -> list[str]:
    """按「路径深度浅 + 命中高价值关键词」排序，保证抓到的是代表性页面。"""
    root_host = urlparse(root).netloc.lower().removeprefix("www.")

    def key(u: str):
        parts = urlparse(u)
        p = parts.path or "/"
        depth = len([x for x in p.split("/") if x])
        hit = 0 if any(k in u.lower() for k in PRIORITY) else 1
        # 主域优先于 chat./status. 这类子域：GEO 要看的是内容页，不是应用入口
        subdomain = 0 if parts.netloc.lower().removeprefix("www.") == root_host else 1
        return (0 if u.rstrip("/") == root.rstrip("/") else 1, subdomain, hit, depth, len(u))

    # 去掉非网页链接，并按去掉末尾斜杠后的形态去重（/about 和 /about/ 是同一页）
    seen: "OrderedDict[str, str]" = OrderedDict()
    for u in [root] + urls:
        if not G.is_fetchable(u):
            continue
        seen.setdefault(u.rstrip("/") or u, u)
    return sorted(seen.values(), key=key)


def analyze_page(url: str, res: dict) -> dict:
    soup = G.parse_html(res["html"])
    text = G.main_text(soup)
    blocks = G.jsonld(soup)

    h1 = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    h2 = [h.get_text(" ", strip=True) for h in soup.find_all("h2")]
    h3 = [h.get_text(" ", strip=True) for h in soup.find_all("h3")]
    paras = [p for p in soup.find_all("p") if p.get_text(strip=True)]
    lis = soup.find_all("li")
    tables = soup.find_all("table")

    hreflangs = soup.find_all("link", rel=lambda v: v and "alternate" in v, hreflang=True)
    canonical = soup.find("link", rel=lambda v: v and "canonical" in v)
    desc = soup.find("meta", attrs={"name": "description"})
    robots_meta = soup.find("meta", attrs={"name": "robots"})

    # 外链引用（指向站外的正文链接数，粗略衡量证据引用习惯）
    ext = 0
    for a in soup.find_all("a", href=True):
        u = G.normalize_url(url, a["href"])
        if u and u.startswith("http") and not G.same_site(url, u):
            ext += 1

    return {
        "url": url,
        "final_url": res["final_url"],
        "status": res["status"],
        "error": res["error"],
        "title": (soup.title.get_text(" ", strip=True) if soup.title else ""),
        "meta_description": (desc.get("content", "") if desc else ""),
        "meta_robots": (robots_meta.get("content", "") if robots_meta else ""),
        "x_robots_tag": res.get("x_robots_tag", ""),
        "hreflang_count": len(hreflangs),
        "canonical": (canonical.get("href", "") if canonical else ""),
        "lang": (soup.html.get("lang", "") if soup.html else ""),
        "h1": h1,
        "h2": h2,
        "h3_count": len(h3),
        "para_count": len(paras),
        "li_count": len(lis),
        "table_count": len(tables),
        "img_count": len(soup.find_all("img")),
        "external_links": ext,
        "jsonld_types": G.jsonld_types(blocks),
        "jsonld_raw": blocks,
        "word_count": G.word_count(text),
        "language": G.page_language(text, (soup.html.get("lang", "") if soup.html else "")),
        "cjk_ratio": G.cjk_ratio(text),
        "text": text[:20000],
        "fetched_at": G.now_iso(),
    }


# 关注的 AI 抓取器（robots 判定用产品名做 UA 匹配）
AI_BOTS = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot", "PerplexityBot",
           "Bytespider", "Baiduspider", "Sogou web spider", "YisouSpider", "Google-Extended"]

# UA 差异探测用的真实 UA 串（各家公开文档口径）：robots 放行 ≠ WAF/CDN 放行，
# 普通浏览器 200 而 AI 爬虫 403 的站，在引擎侧等于不存在，且站长自己看不出来
AI_UA_PROBES = {
    "GPTBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
              "GPTBot/1.2; +https://openai.com/gptbot",
    "ClaudeBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                 "ClaudeBot/1.0; +claudebot@anthropic.com",
    "PerplexityBot": "Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko); compatible; "
                     "PerplexityBot/1.0; +https://perplexity.ai/perplexitybot",
    "Bytespider": "Mozilla/5.0 (Linux; Android 5.0) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Mobile Safari/537.36 (compatible; Bytespider; spider-feedback@bytedance.com)",
}


def check_robots(robots_txt: str, sample_paths: list[str]) -> tuple[list[str], list[dict]]:
    """返回 (整站封禁的 AI 爬虫, 部分路径封禁 [{bot, rule, paths, count}])。"""
    groups = G.robots_parse(robots_txt)
    blocked, partial = [], []
    for bot in AI_BOTS:
        ok_root, rule = G.robots_decision(groups, bot, "/")
        if not ok_root:
            blocked.append(bot)
            continue
        bad = []
        for p in sample_paths:
            ok, r = G.robots_decision(groups, bot, p)
            if not ok:
                bad.append((p, r))
        if bad:
            partial.append({"bot": bot, "rule": bad[0][1], "paths": [p for p, _ in bad[:3]],
                            "count": len(bad), "sampled": len(sample_paths)})
    return blocked, partial


def probe_ai_ua(root: str, home: dict, robots_txt: str, delay: float) -> tuple[dict, list[str]]:
    """换 AI 爬虫 UA 抓一次首页，检出 WAF/CDN 的差异封锁。
    只对 robots 放行的爬虫探测（robots 都封了的，被 WAF 拦是站长本意，不算问题）；
    普通 UA 拿不到 200 时也不探测，那是站点本身的问题，不是差异封锁。"""
    probe: dict[str, int] = {}
    ua_blocked: list[str] = []
    if (home.get("status") or 0) != 200:
        return probe, ua_blocked
    groups = G.robots_parse(robots_txt)
    for bot, ua in AI_UA_PROBES.items():
        if not G.robots_decision(groups, bot, "/")[0]:
            continue
        res = G.fetch(root, timeout=10, retries=0, ua=ua)
        probe[bot] = res["status"]
        if res["status"] in (401, 403, 406, 429, 451, 503):
            ua_blocked.append(bot)
        time.sleep(delay)
    return probe, ua_blocked


def check_llms_txt(root: str, llms_txt: str, robots_txt: str) -> dict | None:
    """llms.txt 只有指向可抓取的有效页面才有意义：抽样验证里面的链接。"""
    if not llms_txt:
        return None
    urls = []
    for u in re.findall(r"https?://[^\s)\]>\"'`]+", llms_txt):
        u = u.rstrip(".,;:")
        if G.same_site(root, u) and G.is_fetchable(u) and u not in urls:
            urls.append(u)
    groups = G.robots_parse(robots_txt)
    broken, robots_blocked = [], []
    sample = urls[:6]
    for u in sample:
        path = urlparse(u).path or "/"
        bots_denied = [b for b in ("GPTBot", "ClaudeBot", "PerplexityBot")
                       if not G.robots_decision(groups, b, path)[0]]
        if bots_denied:
            robots_blocked.append({"url": u, "bots": bots_denied})
        res = G.fetch(u, timeout=10, retries=0)
        if res["status"] != 200:
            broken.append({"url": u, "status": res["status"]})
        time.sleep(0.3)
    return {"total_links": len(urls), "checked": len(sample),
            "broken": broken, "robots_blocked": robots_blocked}


def check_crawl_health(pages: list[dict]):
    """抓取全灭（目标站挂掉/被 WAF 拦）时直接终止流水线：
    失败页 status=0 照样进均分，会产出「均分 3 分」的误导报告。"""
    if not pages:
        return
    ok = sum(1 for p in pages if p["status"] == 200)
    if ok == 0:
        G.die("抓取失败：没有页面返回 200，检查站点可达性/WAF")
    if len(pages) >= 5 and ok / len(pages) < 0.2:
        G.die(f"抓取失败：仅 {ok}/{len(pages)} 页可访问（<20%），检查 WAF/反爬")


def run(slug: str, max_pages: int | None = None, delay: float = 0.5) -> dict:
    cfg = G.load_config(slug)
    if not G.has_site(cfg):
        G.info("无自有网站项目：跳过抓取（采样、竞品、阵地、内容、验收不受影响）")
        return {"slug": slug, "no_site": True, "pages_crawled": 0, "pages_ok": 0}
    root = cfg["brand"]["site"].rstrip("/")
    limit = max_pages or cfg.get("pages", {}).get("max", 25)
    outdir = G.project_dir(slug) / "evidence"
    (outdir / "html").mkdir(parents=True, exist_ok=True)

    G.info(f"抓取 {root}（上限 {limit} 页）")

    robots_txt = G.fetch_text(G.normalize_url(root, "/robots.txt"))
    llms_txt = G.fetch_text(G.normalize_url(root, "/llms.txt"))
    sitemap_urls = discover_sitemap(root)

    home = G.fetch(root)
    link_urls = discover_links(root, home["html"]) if home["html"] else []

    seeds = [u for u in cfg.get("pages", {}).get("seed", []) if u]
    candidates = rank(seeds + sitemap_urls + link_urls, root)[:limit]

    def crawl_one(i: int, u: str) -> dict:
        res = home if u.rstrip("/") == root else G.fetch(u)
        if res["status"] and res["html"]:
            (outdir / "html" / f"{i:03d}.html").write_text(res["html"], "utf-8")
        page = analyze_page(u, res)
        page["snapshot"] = f"evidence/html/{i:03d}.html"
        return page

    # 按 host 分组：组内串行保持礼貌延迟，组间并发（不同站点互不打扰）。
    # 多 host 来源：sitemap/内链里可能混着 chat./docs. 这类子域。
    groups: "OrderedDict[str, list[tuple[int, str]]]" = OrderedDict()
    for i, u in enumerate(candidates, 1):
        groups.setdefault(urlparse(u).netloc.lower(), []).append((i, u))

    def crawl_group(items: list[tuple[int, str]]) -> dict[int, dict]:
        out = {}
        for i, u in items:
            page = crawl_one(i, u)
            out[i] = page
            G.info(f"  [{i}/{len(candidates)}] {page['status']} {u}")
            time.sleep(delay)
        return out

    pages_by_idx: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(3, len(groups)))) as pool:
        for out in pool.map(crawl_group, groups.values()):
            pages_by_idx.update(out)
    pages = [pages_by_idx[i] for i in range(1, len(candidates) + 1)]

    # AI 抓取器是否被 robots 拦截（GEO 的第一道门槛）。
    # 按 RFC 9309 语义判：通配符组封禁、多 UA 共享组、specificity 覆盖都能检出。
    blocked, partial = check_robots(robots_txt, [urlparse(u).path or "/" for u in candidates[:12]])
    # WAF/CDN 差异封锁：robots 说放行不代表真放行，换 AI 爬虫的 UA 实测一次
    ua_probe, ua_blocked = probe_ai_ua(root, home, robots_txt, delay)
    llms_check = check_llms_txt(root, llms_txt, robots_txt)

    # 索引污染：sitemap 里的带参/搜索/翻页 URL 会把低质片段灌进检索索引，
    # 稀释实体表征——sitemap 该只装值得被引用的规范页
    noisy = [u for u in sitemap_urls
             if "?" in u or re.search(r"/(search|tag|page/\d+|sessions?)($|/|\?)", u, re.I)]

    site = {
        "slug": slug,
        "root": root,
        "crawled_at": G.now_iso(),
        "has_robots": bool(robots_txt),
        "has_llms_txt": bool(llms_txt),
        "has_sitemap": bool(sitemap_urls),
        "sitemap_url_count": len(sitemap_urls),
        "robots_sitemap_declared": bool(re.search(r"(?im)^\s*sitemap:", robots_txt or "")),
        "sitemap_noisy_urls": len(noisy),
        "sitemap_noisy_example": (noisy[0] if noisy else None),
        "ai_bots_blocked": blocked,
        "ai_bots_partial": partial,
        "ai_ua_probe": ua_probe,
        "ai_ua_blocked": ua_blocked,
        "llms_txt_check": llms_check,
        "pages_crawled": len(pages),
        "pages_ok": sum(1 for p in pages if p["status"] == 200),
    }
    G.write_json(outdir / "site.json", site)
    G.write_jsonl(outdir / "pages.jsonl", pages)
    G.info(f"完成：{site['pages_ok']}/{len(pages)} 页可访问 → {outdir}")
    check_crawl_health(pages)
    return site


if __name__ == "__main__":
    import sys

    run(sys.argv[1])
