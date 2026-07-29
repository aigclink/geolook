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

    # AI 抓取器是否被 robots 拦截（GEO 的第一道门槛）
    ai_bots = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "PerplexityBot", "Bytespider",
               "Baiduspider", "Sogou web spider", "YisouSpider", "Google-Extended"]
    blocked = []
    for bot in ai_bots:
        m = re.search(rf"(?is)user-agent:\s*{re.escape(bot)}\s*(.*?)(?=\nuser-agent:|\Z)", robots_txt or "")
        if m and re.search(r"(?im)^\s*disallow:\s*/\s*$", m.group(1)):
            blocked.append(bot)

    site = {
        "slug": slug,
        "root": root,
        "crawled_at": G.now_iso(),
        "has_robots": bool(robots_txt),
        "has_llms_txt": bool(llms_txt),
        "has_sitemap": bool(sitemap_urls),
        "sitemap_url_count": len(sitemap_urls),
        "ai_bots_blocked": blocked,
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
