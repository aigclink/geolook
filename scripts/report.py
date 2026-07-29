"""生成本期 GEO 报告：Markdown + 自包含 HTML，并和上一期对比出 delta。

产物：
  work/<slug>/reports/<日期>/report.md
  work/<slug>/reports/<日期>/report.html
  work/<slug>/reports/latest.md（软链接式副本，方便 Claude 每次直接读）
"""

from __future__ import annotations

import html
import re
from pathlib import Path

import geolib as G

GRADE_NOTE = {"A": "可直接被引用", "B": "基本可用", "C": "需要改造", "D": "等于不存在"}


def cell(s) -> str:
    """表格单元格转义：竖线会破 Markdown 表格，换行同理。"""
    return re.sub(r"\s+", " ", str(s)).replace("|", "／").strip()


def prev_metrics(pdir: Path, current: str):
    files = sorted((pdir / "metrics").glob("*.json"))
    files = [f for f in files if f.stem != current]
    return G.read_json(files[-1], None) if files else None


def prev_audit(pdir: Path):
    hist = sorted((pdir / "history").glob("audit-*.json"))
    return G.read_json(hist[-1], None) if hist else None


def delta(cur, prev, pct=False):
    if prev is None or cur is None:
        return ""
    d = cur - prev
    if abs(d) < 1e-9:
        return " (持平)"
    arrow = "↑" if d > 0 else "↓"
    return f" ({arrow}{abs(d)*100:.1f}pp)" if pct else f" ({arrow}{abs(d):.1f})"


def pct(v):
    """指标 None = 未测（比如该平台只采了点名品牌的验证题），不编数。"""
    return f"{v:.0%}" if isinstance(v, (int, float)) else "未测"


def collect_todos(audit: dict, top: int = 20) -> list[dict]:
    """把页面级 issue 汇总成按优先级排好的待办。"""
    buckets: dict[tuple[str, str], list[str]] = {}
    for issue in audit.get("site_issues", []):
        pri, _, body = issue.partition(" ")
        buckets.setdefault((pri, body), []).append("站点级")
    for p in audit.get("pages", []):
        for issue in p.get("issues", []):
            pri, _, body = issue.partition(" ")
            buckets.setdefault((pri, body), []).append(p["url"])
    todos = [
        {"priority": k[0], "action": k[1], "affected": len(v), "examples": v[:3]}
        for k, v in buckets.items()
    ]
    order = {"P0": 0, "P1": 1, "P2": 2}
    todos.sort(key=lambda t: (order.get(t["priority"], 9), -t["affected"]))
    return todos[:top]


def _bench_section(cn_domains: dict[str, int]) -> str:
    """把本期国内信源和 CN-GEO 全国大盘对照，指出高杠杆缺口。"""
    import benchmark

    b = benchmark.compare(cn_domains)
    L = ["#### 与全国大盘对照", "",
         f"CN-GEO 实测的 15 个「跨平台通吃」信源里，本期你占了 **{len(b['cross_platform_covered'])}/15**"
         f"（{b['coverage_rate']:.0%}）。这类域名覆盖全部 11 个平台端，一次投入全平台受益。", ""]

    if b["cross_platform_missing"]:
        L += ["**还没占到的（按全国引用量排序，越靠前越该先做）**：", "",
              "| 域名 | 类型 | 全国引用量 |", "|---|---|---:|"]
        for m in b["cross_platform_missing"][:10]:
            L.append(f"| `{m['domain']}` | {m['category']} | {m['national_citations']:,} |")
        L.append("")

    if b["ecosystem_gaps"]:
        L += ["**平台生态门槛未跨过**（不进这些站，对应平台基本进不去）：", ""]
        for g in b["ecosystem_gaps"]:
            L.append(f"- `{g['domain']}` — {g['why']}")
        L.append("")

    if b["high_position_hits"]:
        L += ["**已占到且引用位置靠前的**（值得加码）：", ""]
        for h in b["high_position_hits"]:
            L.append(f"- `{h['domain']}`（全国平均引用位置 {h['position']}，本期被引 {h['your_citations']} 次）")
        L.append("")

    L += ["> 提醒：**品牌官网类信源只占全库引用的 1.37%**。官网是事实源不是引用源，",
          "> 把力气从「官网再优化」转到「外部信源」通常回报更高。依据见 `references/cn-source-ranking.md`。", ""]
    return "\n".join(L)


def build_markdown(cfg, audit, metrics, prev_m, prev_a, todos) -> str:
    b = cfg["brand"]
    L = []
    A = L.append
    A(f"# {b['name']} · GEO 执行报告 · {G.today()}")
    A("")
    A(f"- 官网：{b['site']}")
    A(f"- 市场：{ {'cn':'国内','global':'海外','both':'国内+海外'}.get(cfg.get('market','cn'), cfg.get('market')) }")
    A(f"- 本期抓取：{audit['page_count']} 页；站点均分 **{audit['avg_score']}**"
      + (delta(audit["avg_score"], prev_a["avg_score"]) if prev_a else " （首期基线）"))
    A("")

    A("## 一、结论先行")
    A("")
    p0 = [t for t in todos if t["priority"] == "P0"]
    if p0:
        A("本期必须先解决的 P0：")
        for t in p0[:5]:
            A(f"- **{t['action']}** — 影响 {t['affected']} 处")
    else:
        A("- 没有 P0 阻塞项，重心转向内容抽取块和外部信源建设。")
    A("")
    if metrics and metrics.get("platforms"):
        for mk, mk_name in (("cn", "国内"), ("global", "海外")):
            pool = [(p, m) for p, m in metrics["platforms"].items()
                    if m.get("market", "cn") == mk]
            if not pool:
                continue
            rows = [(p, m) for p, m in pool if m.get("mention_rate") is not None]
            if not rows:
                A(f"- {mk_name}：未测")
                continue
            best = max(rows, key=lambda x: x[1]["mention_rate"])
            worst = min(rows, key=lambda x: x[1]["mention_rate"])
            if len(rows) < 2 or best[1]["mention_rate"] == worst[1]["mention_rate"]:
                A(f"- {mk_name}：各平台提及率无差异或样本不足，不下结论")
                continue
            A(f"- {mk_name}最好：**{best[1].get('label', best[0])}**（提及率 {best[1]['mention_rate']:.0%}）；"
              f"最弱：**{worst[1].get('label', worst[0])}**（{worst[1]['mention_rate']:.0%}）")
    A("")

    A("## 二、站点技术底座")
    A("")
    s = audit.get("site", {})
    A("| 检查项 | 结果 |")
    A("|---|---|")
    A(f"| sitemap.xml | {'有（' + str(s.get('sitemap_url_count', 0)) + ' 条 URL）' if s.get('has_sitemap') else '**无**'} |")
    A(f"| llms.txt | {'有' if s.get('has_llms_txt') else '**无**'} |")
    A(f"| robots 封禁 AI 抓取器 | {'、'.join(s.get('ai_bots_blocked') or []) or '无'} |")
    A(f"| 页面可访问率 | {s.get('pages_ok', 0)}/{s.get('pages_crawled', 0)} |")
    lc = audit.get("language_coverage") or {}
    if lc:
        lang_line = f"中文 {lc.get('zh_pages', 0)} 页 / 英文 {lc.get('en_pages', 0)} 页"
        if lc.get("ja_pages", 0) > 0:
            lang_line += f" / 日文 {lc['ja_pages']} 页"
        A(f"| 有效内容页语言 | {lang_line} |")
    A("")
    if audit.get("site_issues"):
        for i in audit["site_issues"]:
            A(f"- {i}")
        A("")

    A("## 三、页面 GEO 体检")
    A("")
    gd = audit["grade_distribution"]
    A("| 等级 | 页数 | 含义 |")
    A("|---|---:|---|")
    for g in "ABCD":
        A(f"| {g} | {gd.get(g, 0)} | {GRADE_NOTE[g]} |")
    A("")
    A("最需要改造的页面（分数从低到高）：")
    A("")
    A("| 分数 | 词数 | 缺失抽取块 | 页面 |")
    A("|---:|---:|---|---|")
    for p in audit["pages"][:12]:
        miss = "、".join([k for k, v in p["blocks"].items() if not v]) or "—"
        label = cell(p["title"] or p["url"])[:40]
        A(f"| {p['score']} | {p['word_count']} | {miss} | [{label}]({p['url']}) |")
    A("")
    A("全站抽取块缺口（GEO 最大的杠杆点）：")
    A("")
    A("| 抽取块 | 缺失页数 | 实测增益 |")
    A("|---|---:|---|")
    gain = {"数字事实": "+61.6%", "定义": "+57.3%", "对比": "+55.3%", "操作步骤": "+41.2%", "FAQ": "无显著增益，但利于问答召回"}
    for g in audit["block_gap"]:
        A(f"| {g['block']} | {g['missing_pages']}/{g['total']} | {gain.get(g['block'], '—')} |")
    A("")

    A("## 四、AI 答案可见性")
    A("")
    if not metrics or not metrics.get("platforms"):
        A("本期没有采样数据。API 平台配好 Key 后跑 `sample`，网页端平台用 `sample-sheet` 导出人工采样表。")
        A("")
    else:
        stale = metrics.get("date") and metrics["date"] != G.today()
        A(f"样本量 {metrics['sample_count']} 条 / 问题 {metrics['question_count']} 个"
          + (f"，采样日期 **{metrics['date']}**（非本期，体检与采样节奏不同步属正常）。" if stale else "。"))
        A("")
        A("> 国内和海外是两套独立战场，指标分开算、不合并平均。"
          "同一平台的 API 与网页端、Web 与 App 也各记各的。")
        A("")
        # 国内 / 海外分开成表：跨市场求平均没有任何解释力
        for mk, mk_name in (("cn", "国内"), ("global", "海外")):
            rows = {p: m for p, m in metrics["platforms"].items() if m.get("market", "cn") == mk}
            if not rows:
                continue
            A(f"### {mk_name}市场")
            A("")
            A("**无提示可见性**（问题里不出现品牌名，考的是 AI 会不会主动想到你）：")
            A("")
            A("| 平台 | 样本 | 提及率 | 首位率 | Top3 | 均排名 | 引用官网率 |")
            A("|---|---:|---:|---:|---:|---:|---:|")
            for plat, m in rows.items():
                pm = (prev_m or {}).get("platforms", {}).get(plat, {})
                A(f"| {cell(m.get('label', plat))} | {m['samples']} "
                  f"| {pct(m.get('mention_rate'))}{delta(m.get('mention_rate'), pm.get('mention_rate'), True)} "
                  f"| {pct(m.get('top1_rate'))} | {pct(m.get('top3_rate'))} "
                  f"| {m['avg_rank'] or '—'} | {pct(m.get('own_domain_cite_rate'))} |")
            A("")
            probes = {p: m["probe"] for p, m in rows.items() if (m.get("probe") or {}).get("samples")}
            if probes:
                A("**品牌认知**（直接点名品牌提问，考的是 AI 认不认识你、答得对不对）：")
                A("")
                A("| 平台 | 样本 | 认出品牌 | 引用官网 |")
                A("|---|---:|---:|---:|")
                for plat, pr in probes.items():
                    A(f"| {cell(rows[plat].get('label', plat))} | {pr['samples']} "
                      f"| {pr['recognized_rate']:.0%} | {pr['own_domain_cite_rate']:.0%} |")
                A("")
                A("> 这两张表必须分开看。点名提问时答案必然复述品牌名，混进提及率就是假阳性。")
                A("")

            comp: dict[str, int] = {}
            doms: dict[str, int] = {}
            for m in rows.values():
                for k, v in m["competitor_mentions"].items():
                    comp[k] = comp.get(k, 0) + v
                for k, v in m["top_cited_domains"].items():
                    doms[k] = doms.get(k, 0) + v
            if comp:
                A(f"{mk_name}竞品被提及次数：" + "、".join(f"{k} {v}" for k, v in sorted(comp.items(), key=lambda x: -x[1])[:10]))
                A("")
            if doms:
                A(f"{mk_name} AI 实际引用的信源域名 Top（这就是你该去铺内容的地方）：")
                A("")
                for k, v in sorted(doms.items(), key=lambda x: -x[1])[:15]:
                    A(f"- `{k}` × {v}")
                A("")
            if mk == "cn" and doms:
                A(_bench_section(doms))

    A("## 五、本期待办")
    A("")
    A("| 优先级 | 动作 | 影响面 | 示例 |")
    A("|---|---|---:|---|")
    for t in todos:
        ex = t["examples"][0] if t["examples"] else ""
        ex = ex if ex == "站点级" else f"[链接]({ex})"
        A(f"| {t['priority']} | {cell(t['action'])} | {t['affected']} | {ex} |")
    A("")
    A("---")
    A("")
    A(f"评分口径见 `references/method.md`。生成时间 {G.now_iso()}。")
    return "\n".join(L)


def market_avg_cards(metrics) -> list[tuple[str, str]]:
    """国内/海外平均提及率分开两张卡，各按各市场非 None 值平均；全 None 显示未测。"""
    cards = []
    if not metrics or not metrics.get("platforms"):
        return cards
    for mk, mk_name in (("cn", "国内"), ("global", "海外")):
        pool = [m for m in metrics["platforms"].values() if m.get("market", "cn") == mk]
        if not pool:
            continue
        rates = [m["mention_rate"] for m in pool if m.get("mention_rate") is not None]
        cards.append((f"{mk_name}平均提及率",
                      f"{sum(rates)/len(rates):.0%}" if rates else "未测"))
    return cards


CSS = """
:root{--bg:#fdfcfa;--fg:#1f2328;--mut:#6b7280;--line:#e5e1d8;--acc:#1f4e79;--warn:#b4451f;--card:#fff}
@media(prefers-color-scheme:dark){:root{--bg:#14161a;--fg:#e6e6e6;--mut:#9aa0a6;--line:#2c3037;--acc:#7fb3e0;--warn:#e08b5f;--card:#1b1e23}}
:root[data-theme=dark]{--bg:#14161a;--fg:#e6e6e6;--mut:#9aa0a6;--line:#2c3037;--acc:#7fb3e0;--warn:#e08b5f;--card:#1b1e23}
:root[data-theme=light]{--bg:#fdfcfa;--fg:#1f2328;--mut:#6b7280;--line:#e5e1d8;--acc:#1f4e79;--warn:#b4451f;--card:#fff}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.75 -apple-system,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:920px;margin:0 auto;padding:40px 24px 96px}
h1{font-size:28px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:20px;margin:44px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line);color:var(--acc)}
h3{font-size:16px;margin:26px 0 10px}
.sub{color:var(--mut);font-size:14px;margin-bottom:28px}
table{border-collapse:collapse;width:100%;margin:14px 0;font-size:14px}
th,td{border:1px solid var(--line);padding:8px 10px;text-align:left;vertical-align:top}
th{background:color-mix(in srgb,var(--acc) 8%,transparent);font-weight:600}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow-x:auto}
code{background:color-mix(in srgb,var(--fg) 8%,transparent);padding:1px 5px;border-radius:4px;font-size:13px}
a{color:var(--acc)}
ul{padding-left:22px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:20px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.card .k{font-size:12px;color:var(--mut)}
.card .v{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums;line-height:1.3}
.p0{color:var(--warn);font-weight:700}
hr{border:0;border-top:1px solid var(--line);margin:36px 0}
"""


def md_to_html(md: str) -> str:
    """够用的 Markdown 子集渲染：标题/表格/列表/链接/粗体/行内码。"""
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
        return s

    out, lines, i = [], md.split("\n"), 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1]):
            aligns = [c.strip() for c in lines[i + 1].strip("|").split("|")]
            head = [c.strip() for c in ln.strip("|").split("|")]
            cls = ["n" if a.endswith(":") else "" for a in aligns]  # ---: 表示右对齐数字列
            rows = []
            i += 2
            while i < len(lines) and lines[i].startswith("|"):
                rows.append([c.strip() for c in lines[i].strip("|").split("|")])
                i += 1
            th = "".join(f'<th class="{c}">{inline(h)}</th>' for h, c in zip(head, cls))
            tb = "".join("<tr>" + "".join(f'<td class="{c}">{inline(v)}</td>' for v, c in zip(r, cls)) + "</tr>" for r in rows)
            out.append(f'<div class="scroll"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>')
            continue
        if m := re.match(r"^(#{1,4})\s+(.*)", ln):
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{inline(m.group(2))}</h{lvl}>")
        elif ln.startswith("- "):
            items = []
            while i < len(lines) and lines[i].startswith("- "):
                items.append(f"<li>{inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue
        elif ln.strip() == "---":
            out.append("<hr>")
        elif ln.strip():
            out.append(f"<p>{inline(ln)}</p>")
        i += 1
    body = "\n".join(out)
    body = body.replace("P0 ", '<span class="p0">P0</span> ')
    return body


def build_html(title: str, md: str, cards: list[tuple[str, str]]) -> str:
    card_html = "".join(f'<div class="card"><div class="k">{html.escape(k)}</div><div class="v">{html.escape(v)}</div></div>' for k, v in cards)
    return (
        f"<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
        f'<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body><div class=wrap>"
        f'<div class="cards">{card_html}</div>{md_to_html(md)}</div></body></html>'
    )


def run(slug: str) -> Path:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json")
    if not audit:
        G.die("缺 audit.json，先运行 audit")
    # 优先用当天的采样；没有就回退到最近一期，并在报告里标明日期。
    # （体检可以天天跑，采样通常两周一次，两者日期本来就不会总对齐）
    metrics = G.read_json(pdir / "metrics" / f"{G.today()}.json", None)
    if metrics is None:
        files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
        metrics = G.read_json(files[-1], None) if files else None
    pm = prev_metrics(pdir, metrics["date"] if metrics else G.today())
    pa = prev_audit(pdir)

    todos = collect_todos(audit)
    md = build_markdown(cfg, audit, metrics, pm, pa, todos)

    cards = [
        ("站点均分", str(audit["avg_score"])),
        ("抓取页数", str(audit["page_count"])),
        ("待改造页(C/D)", str(audit["grade_distribution"].get("C", 0) + audit["grade_distribution"].get("D", 0))),
        ("P0 待办", str(sum(1 for t in todos if t["priority"] == "P0"))),
    ]
    cards += market_avg_cards(metrics)

    outdir = pdir / "reports" / G.today()
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.md").write_text(md, "utf-8")
    (outdir / "report.html").write_text(build_html(f"{cfg['brand']['name']} GEO 报告 {G.today()}", md, cards), "utf-8")
    (pdir / "reports" / "latest.md").write_text(md, "utf-8")
    G.write_json(pdir / "todos.json", todos)

    # 归档本期 audit，供下期算 delta
    G.write_json(pdir / "history" / f"audit-{G.today()}.json",
                 {"avg_score": audit["avg_score"], "grade_distribution": audit["grade_distribution"],
                  "page_count": audit["page_count"], "date": G.today()})

    G.info(f"报告已生成 → {outdir/'report.html'}")
    return outdir / "report.html"
