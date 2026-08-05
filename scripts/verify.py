"""验收闭环：重抓站点，自动判定哪些工单真的做完了。

「建议」和「服务」的分界线就在这里——能自动验收的，就不靠人说做完了。
verify 不改内容，只做三件事：重抓 → 跑 checker → 回写 tasks.json 状态。

checker 语法（写在工单的 acceptance.check 里）：
  site.no_ai_bot_block            robots 不再整站封 AI 抓取器
  site.no_ai_ua_block             换 AI 爬虫 UA 探测首页不再被 WAF/CDN 拒绝
  site.robots_sitemap_declared    robots.txt 已声明 Sitemap: 行
  site.llms_txt_valid             llms.txt 抽样链接全部有效且未被 robots 封禁
  site.sitemap_clean              sitemap 不再含带参数/搜索/翻页 URL
  site.hreflang_gte:0.5           多语言内容页 hreflang 覆盖率达标
  site.has_sitemap / has_llms_txt 站点级资产已上线
  site.avg_score_gte:70           重跑 audit 均分达标
  site.en_pages_gte:8             英文有效内容页数达标
  site.lang_balance:0.7           中英页面数差距在阈值内
  pages.static_text               受影响页面正文词数 ≥120（SPA 修复）
  pages.has_jsonld                受影响页面已挂 JSON-LD
  pages.block:定义                缺该抽取块的页面数下降 ≥50%
  pages.wordcount_gte:1000        正文不足 1000 词的页面数下降 ≥40%
  metrics.mention_rate_gte:cn:0.3 指定市场平均无提示提及率达标
  metrics.own_cite_gte:cn:0.1     指定市场引用官网率达标
  external.any:a.com,b.com        采样里出现任一目标域名的引用

相对型指标（下降 X%）用工单的 baseline_count（生成工单时的真实缺口数）当基线；
旧工单没有该字段时退回 affected 列表长度。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import audit as A
import geolib as G
import tasks as T


def report_key(f: Path) -> tuple[str, str]:
    """验收报告排序键：同日旧格式 2026-07-28.json 排在新格式带时分秒的文件之前，
    保证 sorted()[-1] 永远是最新一份（字典序里 '.' > '-'，直接按文件名排会拿错）。"""
    m = re.match(r"(\d{4}-\d{2}-\d{2})(?:-(\d{6}))?", f.stem)
    return (m.group(1), m.group(2) or "000000") if m else ("", f.stem)


def _pages_by_url(audit: dict) -> dict:
    return {p["url"]: p for p in audit.get("pages", [])}


def _cited_domains(metrics: dict, market: str | None = None) -> dict[str, int]:
    out: dict[str, int] = {}
    for m in (metrics or {}).get("platforms", {}).values():
        if market and m.get("market", "cn") != market:
            continue
        for k, v in m.get("top_cited_domains", {}).items():
            out[k] = out.get(k, 0) + v
    return out


def _market_avg(metrics: dict, market: str, field: str):
    # None = 该平台本期未测（只采了点名题），不参与平均；全 None 返回 None，
    # 调用方按「无数据」处理，绝不能默认 0 误判「未达标」。
    vals = [m[field] for m in (metrics or {}).get("platforms", {}).values()
            if m.get("market", "cn") == market and m.get(field) is not None]
    return (sum(vals) / len(vals)) if vals else None


def check(task: dict, audit: dict, metrics: dict) -> tuple[bool | None, str, dict | None]:
    """返回 (通过?, 说明, 进度)。通过 None 表示无法自动判定。

    进度是量化 checker 的结构化快照 {label, cur, target, op, base?, pct?}——
    任务级 before/after 的数据源：首次验收存 progress_first（before），
    每次验收覆盖 progress（after），界面画「基线 → 当前 → 目标」。
    定性 checker（有/无 sitemap 之类）没有中间态，进度为 None。
    """
    acc = task.get("acceptance", {})
    if acc.get("type") != "auto":
        return None, "需人工确认", None
    expr = acc.get("check", "")
    site = audit.get("site", {})
    pages = _pages_by_url(audit)
    aff = task.get("affected", [])
    base = len(aff)

    try:
        if expr == "site.no_ai_bot_block":
            blocked = site.get("ai_bots_blocked") or []
            return (not blocked), ("robots 未封禁任何 AI 抓取器" if not blocked
                                   else f"仍封禁：{'、'.join(blocked)}"), None
        if expr == "site.no_ai_ua_block":
            bad = site.get("ai_ua_blocked") or []
            probe = site.get("ai_ua_probe") or {}
            if not probe and not bad:
                return None, "本次重抓没有 UA 探测数据（旧版抓取结果），先重跑 crawl", None
            return (not bad), ("AI 爬虫 UA 探测首页全部放行" if not bad
                               else f"仍被拒：{'、'.join(bad)}"), None
        if expr == "site.robots_sitemap_declared":
            ok = bool(site.get("robots_sitemap_declared"))
            return ok, ("robots.txt 已声明 Sitemap" if ok else "robots.txt 仍未声明 Sitemap"), None
        if expr == "site.llms_txt_valid":
            if not site.get("has_llms_txt"):
                return False, "llms.txt 缺失", None
            lch = site.get("llms_txt_check") or {}
            if not lch:
                return None, "本次重抓没有 llms.txt 校验数据（旧版抓取结果），先重跑 crawl", None
            nbad = len(lch.get("broken", [])) + len(lch.get("robots_blocked", []))
            return nbad == 0, (f"抽样 {lch.get('checked', 0)} 条链接全部有效" if nbad == 0
                              else f"仍有 {nbad} 条失效/被封链接"), \
                {"label": "llms.txt 失效链接", "cur": nbad, "target": 0, "op": "lte"}
        if expr == "pages.no_noindex":
            bad = [u for u in aff if any(
                c in (pages.get(u, {}).get("issue_codes") or [])
                for c in ("NOINDEX", "XROBOTS_NOINDEX"))]
            return (not bad), f"{base - len(bad)}/{base} 页已去掉 noindex", \
                {"label": "仍带 noindex 的页面", "cur": len(bad), "target": 0, "op": "lte", "base": base}
        if expr == "site.sitemap_clean":
            n = site.get("sitemap_noisy_urls")
            if n is None:
                return None, "本次重抓没有 sitemap 污染统计（旧版抓取结果），先重跑 crawl", None
            return n == 0, (f"sitemap 已无低价值 URL" if n == 0
                            else f"仍有 {n} 条带参数/搜索/翻页 URL"), \
                {"label": "sitemap 低价值 URL", "cur": n, "target": 0, "op": "lte"}
        if expr.startswith("site.hreflang_gte:"):
            tgt = float(expr.split(":")[1])
            lc2 = audit.get("language_coverage") or {}
            total = lc2.get("content_pages") or 0
            if not total or "hreflang_pages" not in lc2:
                return None, "本次体检没有 hreflang 统计（旧版结果），先重跑 crawl + audit", None
            cur = lc2.get("hreflang_pages", 0) / total
            return cur >= tgt, f"hreflang 覆盖 {lc2.get('hreflang_pages', 0)}/{total} 页（{cur:.0%} / 目标 {tgt:.0%}）", \
                {"label": "hreflang 覆盖率", "cur": round(cur, 2), "target": tgt, "op": "gte", "pct": True}
        if expr == "site.has_sitemap":
            ok = bool(site.get("has_sitemap"))
            return ok, f"sitemap {'已上线（%d 条 URL）' % site.get('sitemap_url_count', 0) if ok else '仍缺失'}", None
        if expr == "site.has_llms_txt":
            ok = bool(site.get("has_llms_txt"))
            return ok, ("llms.txt 已上线" if ok else "llms.txt 仍缺失"), None
        if expr.startswith("site.avg_score_gte:"):
            tgt = float(expr.split(":")[1])
            cur = audit.get("avg_score", 0)
            return cur >= tgt, f"当前均分 {cur} / 目标 {tgt}", \
                {"label": "站点体检均分", "cur": cur, "target": tgt, "op": "gte"}
        if expr.startswith("site.en_pages_gte:"):
            tgt = int(expr.split(":")[1])
            cur = (audit.get("language_coverage") or {}).get("en_pages", 0)
            return cur >= tgt, f"英文有效内容页 {cur} / 目标 {tgt}", \
                {"label": "英文有效内容页", "cur": cur, "target": tgt, "op": "gte"}
        if expr.startswith("site.lang_balance:"):
            r = float(expr.split(":")[1])
            lc = audit.get("language_coverage") or {}
            en, zh = lc.get("en_pages", 0), lc.get("zh_pages", 0)
            if not (en and zh):
                return False, f"中文 {zh} 页 / 英文 {en} 页，仍有一侧为空", None
            ok = abs(en - zh) <= max(en, zh) * r
            return ok, f"中文 {zh} 页 / 英文 {en} 页", \
                {"label": "中英页数差比", "cur": round(abs(en - zh) / max(en, zh), 2),
                 "target": r, "op": "lte"}

        if expr == "pages.static_text":
            # 功能页（登录/联系页等）天然低词数，和 audit 用同一条规则豁免，
            # 否则一张 SPA 空壳工单会被联系页永远卡在未达标
            aff_real = [u for u in aff if not A.FUNC_PAGE.search(urlparse(u).path)]
            bad = [u for u in aff_real if pages.get(u, {}).get("word_count", 0) < 120]
            return (not bad), f"{base - len(bad)}/{base} 页已能抓到正文", \
                {"label": "抓不到正文的页面", "cur": len(bad), "target": 0, "op": "lte", "base": base}
        if expr == "pages.has_jsonld":
            bad = [u for u in aff if not pages.get(u, {}).get("jsonld_types")]
            return (not bad), f"{base - len(bad)}/{base} 页已挂 JSON-LD", \
                {"label": "未挂 JSON-LD 的页面", "cur": len(bad), "target": 0, "op": "lte", "base": base}
        if expr.startswith("pages.block:"):
            blk = expr.split(":", 1)[1]
            # 基线用生成工单时的真实缺口数；旧工单没有该字段退回 affected 长度
            base = task.get("baseline_count", len(aff))
            cur = sum(1 for p in audit.get("pages", []) if not p["blocks"].get(blk))
            return cur <= base * 0.5, f"缺「{blk}」页面 {cur}（基线 {base}，目标 ≤{int(base*0.5)}）", \
                {"label": f"缺「{blk}」块的页面", "cur": cur, "target": int(base * 0.5),
                 "op": "lte", "base": base}
        if expr.startswith("pages.wordcount_gte:"):
            n = int(expr.split(":")[1])
            base = task.get("baseline_count", len(aff))
            cur = sum(1 for p in audit.get("pages", []) if 100 <= p["word_count"] < n)
            return cur <= base * 0.6, f"正文 <{n} 词的页面 {cur}（基线 {base}，目标 ≤{int(base*0.6)}）", \
                {"label": f"正文不足 {n} 词的页面", "cur": cur, "target": int(base * 0.6),
                 "op": "lte", "base": base}

        if expr.startswith("metrics.mention_rate_gte:"):
            _, mk, tgt = expr.split(":")
            cur = _market_avg(metrics, mk, "mention_rate")
            if cur is None:
                return None, f"{mk} 市场本期无采样数据", None
            return cur >= float(tgt), f"{mk} 平均提及率 {cur:.1%} / 目标 {float(tgt):.0%}", \
                {"label": f"{mk} 平均提及率", "cur": round(cur, 3), "target": float(tgt),
                 "op": "gte", "pct": True}
        if expr.startswith("metrics.own_cite_gte:"):
            _, mk, tgt = expr.split(":")
            cur = _market_avg(metrics, mk, "own_domain_cite_rate")
            if cur is None:
                return None, f"{mk} 市场本期无采样数据", None
            return cur >= float(tgt), f"{mk} 引用官网率 {cur:.1%} / 目标 {float(tgt):.0%}", \
                {"label": f"{mk} 引用官网率", "cur": round(cur, 3), "target": float(tgt),
                 "op": "gte", "pct": True}

        if expr.startswith("external.any:"):
            targets = [d.strip() for d in expr.split(":", 1)[1].split(",") if d.strip()]
            doms = _cited_domains(metrics)
            hit = [t for t in targets if any(d == t or d.endswith("." + t) for d in doms)]
            return bool(hit), (f"已被引用：{'、'.join(hit)}" if hit
                               else f"目标域名均未出现在采样引用中（{len(targets)} 个）"), \
                {"label": "目标域名被引用数", "cur": len(hit), "target": 1, "op": "gte",
                 "base": len(targets)}
    except Exception as e:  # noqa: BLE001
        return None, f"检查器出错：{type(e).__name__}: {e}", None
    return None, f"未知检查器 `{expr}`", None


def run(slug: str, recrawl: bool = True) -> dict:
    pdir = G.project_dir(slug)
    if recrawl:
        import audit as A
        import crawl as C
        G.info("=== 重抓站点 ===")
        C.run(slug)
        G.info("=== 重跑体检 ===")
        A.run(slug)

    audit = G.read_json(pdir / "audit.json", {})
    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], None) if files else None

    results, changed = [], 0
    with G.project_lock(slug):
        data = T.load(slug)
        if not data.get("tasks"):
            G.die("还没有工单，先运行：python3 scripts/geo.py plan --slug " + slug)

        for t in data["tasks"]:
            ok, note, prog = check(t, audit, metrics)
            prev = t["status"]
            if prog:
                prog["at"] = G.now_iso()
                t.setdefault("progress_first", dict(prog))  # 首次验收快照 = before
                t["progress"] = prog                        # 最近一次 = after
            if ok is True and t["status"] != "done":
                t["status"] = "done"
                t["closed_at"] = G.now_iso()
                changed += 1
            elif ok is False and t["status"] == "done":
                # 回归了：之前验收通过，现在又不达标
                t["status"] = "todo"
                t["closed_at"] = None
                changed += 1
            t["evidence"].append({"at": G.now_iso(), "check": t["acceptance"].get("check"),
                                  "result": {True: "pass", False: "fail", None: "manual"}[ok], "note": note})
            t["evidence"] = t["evidence"][-6:]  # 只留最近 6 条，别把文件撑爆
            results.append({"id": t["id"], "title": t["title"], "priority": t["priority"],
                            "market": t["market"], "package": t["package"],
                            "verdict": {True: "通过", False: "未达标", None: "待人工"}[ok],
                            "note": note, "was": prev, "now": t["status"],
                            "progress": prog, "progress_first": t.get("progress_first")})

        T.save(slug, data)
    report = {
        "slug": slug, "verified_at": G.now_iso(),
        "audit_avg_score": audit.get("avg_score"),
        "metrics_date": metrics.get("date") if metrics else None,
        "changed": changed,
        "summary": data["summary"],
        "results": results,
    }
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")  # 一天验多次不互相覆盖
    G.write_json(pdir / "verify" / f"{stamp}.json", report)

    p = sum(1 for r in results if r["verdict"] == "通过")
    f = sum(1 for r in results if r["verdict"] == "未达标")
    m = sum(1 for r in results if r["verdict"] == "待人工")
    G.info(f"验收：通过 {p} / 未达标 {f} / 待人工 {m}；状态变更 {changed} 条")
    return report
