#!/usr/bin/env python3
"""GEO 自动化管线 CLI。

  python3 scripts/geo.py init --url https://example.com --name 品牌名
  python3 scripts/geo.py crawl        --slug example
  python3 scripts/geo.py audit        --slug example
  python3 scripts/geo.py sample       --slug example
  python3 scripts/geo.py sample-sheet --slug example
  python3 scripts/geo.py sample-import --slug example --file work/example/samples/2026-07-26-manual.md
  python3 scripts/geo.py report       --slug example
  python3 scripts/geo.py cycle        --slug example      # 一条命令跑完整期
  python3 scripts/geo.py list
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import geolib as G  # noqa: E402
except ModuleNotFoundError as e:
    raise SystemExit(f"缺少依赖：{e.name}。请先 pip3 install requests beautifulsoup4 lxml") from e


DEFAULT_PLATFORMS = {
    "cn": ["glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu"],
    "global": ["gemini", "openai", "claude", "grok", "perplexity", "chatgpt"],
    "both": ["glm", "doubao", "deepseek", "kimi", "minimax", "nano_ai", "baidu",
             "gemini", "openai", "claude", "grok", "perplexity", "chatgpt"],
}


def cmd_init(a):
    url = a.url.rstrip("/")
    if not url.startswith("http"):
        url = "https://" + url
    host = urlparse(url).netloc.removeprefix("www.")
    slug = a.slug or G.slugify(host.split(".")[0])

    # 已存在的项目绝不覆盖：geo.json 里有问题库、竞品、事实口径，
    # 覆盖等于把一期的人工投入清零。要重建必须显式加 --force。
    existing = G.project_dir(slug) / "geo.json"
    if existing.exists() and not getattr(a, "force", False):
        cur = G.read_json(existing, {})
        G.die(f"项目 `{slug}` 已存在（问题 {len(cur.get('questions', []))} 题、"
              f"竞品 {len(cur.get('competitors', []))} 个）。换一个 --slug，"
              f"或确认要清空后加 --force")

    name = a.name
    if not name:
        res = G.fetch(url)
        if res["html"]:
            soup = G.parse_html(res["html"])
            title = soup.title.get_text(" ", strip=True) if soup.title else ""
            name = (title.split("|")[0].split("-")[0].split("_")[0].strip() or host)[:40]
        else:
            name = host

    cfg = {
        "slug": slug,
        "created_at": G.now_iso(),
        "market": a.market,
        "brand": {
            "name": name,
            "aliases": [],
            "site": url,
            "products": [],
            "industry": "",
            "target_users": "",
            "business_goal": "",
        },
        "competitors": [],
        "platforms": DEFAULT_PLATFORMS[a.market],
        "pages": {"seed": [], "max": a.max_pages},
        "questions": [],
        "materials": [],
        "targets": {"mention_rate": 0.5, "top3_rate": 0.3, "avg_page_score": 75},
        "notes": "questions / competitors / aliases 由 Claude 按 SKILL.md 步骤 2 填充",
    }
    G.save_config(slug, cfg)
    for sub in ("evidence", "samples", "metrics", "reports", "history", "content"):
        (G.project_dir(slug) / sub).mkdir(parents=True, exist_ok=True)
    print(f"[geo] 项目已创建：{G.project_dir(slug)/'geo.json'}（品牌：{name}）")
    print("[geo] 下一步：让 Claude 补全 brand/competitors/questions，再跑 crawl")
    return cfg


def cmd_bootstrap(a):
    import bootstrap

    bootstrap.run(a.slug, skip_llm=a.skip_llm)


def cmd_deliverables(a):
    import deliverables

    deliverables.run(a.slug)


def cmd_new(a):
    """只给一个网址，跑完全流程出三份交付物。"""
    import audit as A
    import blueprint as BP
    import bootstrap
    import crawl as C
    import deliver
    import deliverables as DV
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    G.info("═══ 1/9 建项目 ═══")
    cfg = cmd_init(a)
    slug = cfg["slug"]
    G.info("═══ 2/9 抓取官网 ═══")
    C.run(slug, max_pages=a.max_pages)
    G.info("═══ 3/9 体检 ═══")
    A.run(slug)
    G.info("═══ 4/9 自动推导品牌事实、竞品与问题库 ═══")
    bootstrap.run(slug, skip_llm=a.skip_llm)
    G.info("═══ 5/9 重跑体检（问题库影响对题性评分）═══")
    A.run(slug)
    G.info("═══ 6/9 AI 答案采样 ═══")
    if a.no_sample:
        G.info("跳过：--no-sample")
    elif not G.load_config(slug).get("questions"):
        G.info("跳过：问题库为空")
    else:
        try:
            S.run(slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    G.info("═══ 7/9 工单与建设蓝图 ═══")
    tasks.build(slug)
    BP.build(slug)
    G.info("═══ 8/9 资产与报告 ═══")
    generate.run(slug, with_draft=a.draft, draft_limit=a.draft_limit)
    Rp.run(slug)
    G.info("═══ 9/9 三份交付物 + 交付包 ═══")
    DV.run(slug)
    try:
        V.run(slug, recrawl=False)
    except Exception as e:  # noqa: BLE001
        G.info(f"验收失败：{e}")
    deliver.run(slug)
    G.info("")
    G.info(f"完成。交付物在 work/{slug}/deliverables/：")
    G.info("  1-GEO診斷報告.html   現在什麼樣")
    G.info("  2-GEO最佳化方案.html   應該改成什麼樣")
    G.info("  3-GEO執行方案.html   誰在什麼時候做什麼")
    G.info("")
    G.info("下一步：打开工作台核对自动推导的品牌事实与问题库（标「待确认」的需人工补齐）")
    G.info("  python3 scripts/geo.py ui")


def cmd_autopilot(a):
    """对已建好的项目跑完整引导：推导底座 → 采样 → 工单 → 资产 → 三份交付物。"""
    import audit as A
    import blueprint as BP
    import bootstrap
    import crawl as C
    import deliver
    import deliverables as DV
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    cfg = G.load_config(a.slug)
    G.info("═══ 1/8 抓取官网 ═══")
    C.run(a.slug)
    G.info("═══ 2/8 体检 ═══")
    A.run(a.slug)
    if not cfg.get("questions"):
        G.info("═══ 3/8 自动推导品牌事实、竞品与问题库 ═══")
        bootstrap.run(a.slug, skip_llm=a.skip_llm)
        A.run(a.slug)
    else:
        G.info("═══ 3/8 已有问题库，跳过自动推导 ═══")
    G.info("═══ 4/8 AI 答案采样 ═══")
    if a.no_sample:
        G.info("跳过：--no-sample")
    elif G.load_config(a.slug).get("questions"):
        try:
            S.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    G.info("═══ 5/8 工单与建设蓝图 ═══")
    tasks.build(a.slug)
    BP.build(a.slug)
    G.info("═══ 6/8 资产与报告 ═══")
    generate.run(a.slug)
    Rp.run(a.slug)
    G.info("═══ 7/8 三份交付物 ═══")
    DV.run(a.slug)
    G.info("═══ 8/8 验收与打包 ═══")
    try:
        V.run(a.slug, recrawl=False)
    except Exception as e:  # noqa: BLE001
        G.info(f"验收失败：{e}")
    deliver.run(a.slug)
    G.info("完成。三份交付物在 deliverables/，标「待确认」的品牌事实需人工补齐。")


def cmd_crawl(a):
    import crawl

    crawl.run(a.slug, max_pages=a.max_pages)


def cmd_audit(a):
    import audit

    audit.run(a.slug)


def cmd_sample(a):
    import sample

    sample.run(a.slug, platforms=a.platforms.split(",") if a.platforms else None,
               repeat=a.repeat, limit=a.limit)


def cmd_sheet(a):
    import sample

    sample.sheet(a.slug)


def cmd_import(a):
    import sample

    sample.sample_import(a.slug, a.file)


def cmd_report(a):
    import report

    report.run(a.slug)


def cmd_cycle(a):
    import audit
    import crawl
    import report
    import sample

    G.info("=== 1/4 抓取 ===")
    crawl.run(a.slug, max_pages=a.max_pages)
    G.info("=== 2/4 体检 ===")
    audit.run(a.slug)
    G.info("=== 3/4 采样 ===")
    # 采样失败不能把整期带崩：报告和待办比采样更重要
    if not G.load_config(a.slug).get("questions"):
        G.info("跳过采样：geo.json 里还没有问题库（见 SKILL.md 步骤 2）")
    else:
        try:
            sample.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    G.info("=== 4/4 报告 ===")
    report.run(a.slug)


def cmd_expand(a):
    import expand
    expand.run(a.slug, use_llm=not a.no_llm)


def cmd_plan(a):
    import tasks

    tasks.build(a.slug)


def cmd_blueprint(a):
    import blueprint

    blueprint.build(a.slug)


def cmd_generate(a):
    import generate

    generate.run(a.slug, which=a.asset.split(",") if a.asset else None,
                 with_draft=a.draft, draft_limit=a.draft_limit)


def cmd_lint(a):
    import generate

    rep = generate.lint_all(a.slug)
    if not rep["files"]:
        print("没有 AI 初稿可检查（用 generate --draft 生成）")
        return
    print(f"\n检查 {len(rep['files'])} 份初稿，共 {rep['total_issues']} 项待核实（高风险 {rep['high']} 项）")
    for fn, issues in rep["files"].items():
        if not issues:
            print(f"\n  {fn}：无风险")
            continue
        print(f"\n  {fn}")
        for i in issues:
            print(f"    [{i['level']}] {i['type']}：{i['detail']}")
            print(f"          …{i['excerpt'][:76]}")
    print("\n高风险项必须处理后才能发布；未核实数字需补来源与核验日期。\n")


def cmd_verify(a):
    import verify

    verify.run(a.slug, recrawl=not a.no_recrawl)


def cmd_deliver(a):
    import deliver

    deliver.run(a.slug)


def cmd_publish(a):
    import publish

    r = publish.publish(a.slug, a.platform, a.path, a.title or "")
    if r.get("ok"):
        G.info(f"已发布：{r.get('url') or r.get('note') or 'ok'}")
    else:
        G.die(f"发布失败：{r.get('error')}")


def cmd_task(a):
    import tasks

    if a.status:
        try:
            tasks.set_status(a.slug, a.id, a.status, a.note or "")
        except KeyError as e:
            G.die(e.args[0] if e.args else str(e))
    else:
        data = tasks.load(a.slug)
        t = next((x for x in data["tasks"] if x["id"] == a.id), None)
        if not t:
            G.die(f"找不到工单 {a.id}")
        print(json.dumps(t, ensure_ascii=False, indent=2))


def cmd_status(a):
    import tasks

    cfg = G.load_config(a.slug)
    audit = G.read_json(G.project_dir(a.slug) / "audit.json", {})
    data = tasks.load(a.slug)
    s = data.get("summary", {})
    print(f"\n{cfg['brand']['name']}  ({cfg.get('market')})  {cfg['brand']['site']}")
    print(f"  站点均分 {audit.get('avg_score', '—')}  页面 {audit.get('page_count', '—')}"
          f"  工单 {s.get('total', 0)} 条（可自动验收 {s.get('auto_verifiable', 0)}）")
    if not data.get("tasks"):
        print("  还没有工单，运行 plan 生成\n")
        return
    order = {"P0": 0, "P1": 1, "P2": 2}
    for pri in ("P0", "P1", "P2"):
        rows = [t for t in data["tasks"] if t["priority"] == pri]
        if not rows:
            continue
        done = sum(1 for t in rows if t["status"] == "done")
        print(f"\n  {pri}  {done}/{len(rows)} 完成")
        for t in sorted(rows, key=lambda x: (x["status"] != "todo", x["package"])):
            mark = {"done": "✓", "doing": "◐", "blocked": "✗", "wontfix": "—"}.get(t["status"], "·")
            print(f"    {mark} {t['id']} [{t['package']}/{t['owner']}/{t['market']}] {t['title']}")
    print()


def cmd_serve(a):
    """一条命令跑完整个服务周期：诊断 → 方案 → 资产 → 验收 → 交付。"""
    import audit as A
    import crawl as C
    import deliver
    import generate
    import report as Rp
    import sample as S
    import tasks
    import verify as V

    G.info("═══ 1/7 抓取 ═══")
    C.run(a.slug, max_pages=a.max_pages)
    G.info("═══ 2/7 体检 ═══")
    A.run(a.slug)
    G.info("═══ 3/7 AI 答案采样 ═══")
    if not G.load_config(a.slug).get("questions"):
        G.info("跳过：问题库为空（见 SKILL.md 步骤 2）")
    elif a.no_sample:
        G.info("跳过：--no-sample")
    else:
        try:
            S.run(a.slug, limit=a.limit)
        except Exception as e:  # noqa: BLE001
            G.info(f"采样跳过：{type(e).__name__}: {e}")
    try:
        import expand
        expand.run(a.slug)
    except Exception as e:  # noqa: BLE001
        G.info(f"拓词跳过：{type(e).__name__}: {e}")
    G.info("═══ 4/7 生成工单与建设蓝图 ═══")
    tasks.build(a.slug)
    import blueprint
    blueprint.build(a.slug)
    G.info("═══ 5/7 生成资产 ═══")
    generate.run(a.slug, with_draft=a.draft, draft_limit=a.draft_limit)
    G.info("═══ 6/7 报告 ═══")
    Rp.run(a.slug)
    G.info("═══ 7/7 验收上期工单 ═══")
    V.run(a.slug, recrawl=False)
    G.info("═══ 打包交付 ═══")
    deliver.run(a.slug)


def cmd_ui(a):
    import dashboard

    dashboard.run(host=a.host, port=a.port, open_browser=not a.no_open)


def cmd_list(a):
    if not G.WORK.exists():
        print("还没有任何项目")
        return
    for d in sorted(G.WORK.iterdir()):
        cfg_path = d / "geo.json"
        if cfg_path.exists():
            cfg = G.read_json(cfg_path, {})
            reports = sorted((d / "reports").glob("2*")) if (d / "reports").exists() else []
            last = reports[-1].name if reports else "—"
            print(f"{d.name:20s} {cfg.get('brand', {}).get('name', ''):22s} 问题 {len(cfg.get('questions', [])):3d}  最近报告 {last}")


def main():
    p = argparse.ArgumentParser(prog="geo", description="GEO 自动化管线")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="新建项目")
    s.add_argument("--url", required=True)
    s.add_argument("--name")
    s.add_argument("--slug")
    s.add_argument("--market", choices=["cn", "global", "both"], default="cn")
    s.add_argument("--max-pages", type=int, default=25, dest="max_pages")
    s.add_argument("--force", action="store_true", help="项目已存在时清空重建（危险）")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("new", help="★ 只给一个网址，全自动出三份交付物")
    s.add_argument("--url", required=True)
    s.add_argument("--name")
    s.add_argument("--slug")
    s.add_argument("--market", choices=["cn", "global", "both"], default="both")
    s.add_argument("--max-pages", type=int, default=25, dest="max_pages")
    s.add_argument("--limit", type=int, default=None, help="采样只跑前 N 题")
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm", help="不用 LLM 推导底座")
    s.add_argument("--draft", action="store_true")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_new)

    s = sub.add_parser("autopilot", help="对已有项目跑完整引导流程")
    s.add_argument("--slug", required=True)
    s.add_argument("--limit", type=int, default=None)
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm")
    s.set_defaults(func=cmd_autopilot)

    s = sub.add_parser("bootstrap", help="从官网正文自动推导品牌事实、竞品与问题库")
    s.add_argument("--slug", required=True)
    s.add_argument("--skip-llm", action="store_true", dest="skip_llm")
    s.set_defaults(func=cmd_bootstrap)

    s = sub.add_parser("deliverables", help="出三份正式交付物（诊断/优化/执行）")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_deliverables)

    s = sub.add_parser("crawl", help="抓取官网")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.set_defaults(func=cmd_crawl)

    s = sub.add_parser("audit", help="页面 GEO 体检")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("sample", help="API 平台答案采样")
    s.add_argument("--slug", required=True)
    s.add_argument("--platforms", help="逗号分隔，默认取 geo.json 里有 Key 的")
    s.add_argument("--repeat", type=int, default=1, help="每题重复采样次数")
    s.add_argument("--limit", type=int, default=None, help="只跑前 N 个问题")
    s.set_defaults(func=cmd_sample)

    s = sub.add_parser("sample-sheet", help="导出人工/浏览器采样表")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_sheet)

    s = sub.add_parser("sample-import", help="导入人工采样表")
    s.add_argument("--slug", required=True)
    s.add_argument("--file", required=True)
    s.set_defaults(func=cmd_import)

    s = sub.add_parser("report", help="生成报告")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("cycle", help="抓取→体检→采样→报告 一次跑完")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.add_argument("--limit", type=int, default=None)
    s.set_defaults(func=cmd_cycle)

    s = sub.add_parser("expand", help="拓词：百度下拉/Google suggest 扩出真实需求候选题")
    s.add_argument("--slug", required=True)
    s.add_argument("--no-llm", action="store_true", dest="no_llm",
                   help="不调 LLM 转写问句，用模板兜底")
    s.set_defaults(func=cmd_expand)

    s = sub.add_parser("plan", help="诊断结果 → 结构化工单（含验收标准）")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_plan)

    s = sub.add_parser("blueprint", help="GEO 建设蓝图：在哪些平台建、建什么内容、覆盖度多少")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_blueprint)

    s = sub.add_parser("generate", help="产出可直接部署的资产（llms.txt/JSON-LD/片段/大纲）")
    s.add_argument("--slug", required=True)
    s.add_argument("--asset", help="逗号分隔：llms,jsonld,snippets,outlines")
    s.add_argument("--draft", action="store_true", help="额外调用 LLM 出文章初稿")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.set_defaults(func=cmd_generate)

    s = sub.add_parser("lint", help="检查 AI 初稿的编造风险（发布/交付前必跑）")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_lint)

    s = sub.add_parser("verify", help="重抓并自动验收工单")
    s.add_argument("--slug", required=True)
    s.add_argument("--no-recrawl", action="store_true", dest="no_recrawl",
                   help="用现有 audit 结果验收，不重新抓站")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("deliver", help="打包客户交付物")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_deliver)

    s = sub.add_parser("publish", help="把成稿/资产发布到已配置的渠道（永远手动触发）")
    s.add_argument("--slug", required=True)
    s.add_argument("--path", required=True, help="content/ 或 assets/ 下的相对路径")
    s.add_argument("--platform", required=True, choices=["github", "wordpress", "wechat_draft", "webhook"])
    s.add_argument("--title")
    s.set_defaults(func=cmd_publish)

    s = sub.add_parser("task", help="查看或更新单条工单状态")
    s.add_argument("--slug", required=True)
    s.add_argument("--id", required=True)
    s.add_argument("--status", choices=["todo", "doing", "done", "blocked", "wontfix"])
    s.add_argument("--note")
    s.set_defaults(func=cmd_task)

    s = sub.add_parser("status", help="项目进度看板")
    s.add_argument("--slug", required=True)
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("serve", help="完整服务周期：抓取→体检→采样→工单→资产→报告→验收→交付")
    s.add_argument("--slug", required=True)
    s.add_argument("--max-pages", type=int, default=None, dest="max_pages")
    s.add_argument("--limit", type=int, default=None, help="采样只跑前 N 个问题")
    s.add_argument("--no-sample", action="store_true", dest="no_sample")
    s.add_argument("--draft", action="store_true", help="额外生成文章初稿")
    s.add_argument("--draft-limit", type=int, default=3, dest="draft_limit")
    s.set_defaults(func=cmd_serve)

    s = sub.add_parser("ui", help="启动可观测看板（趋势、工单、信源、验收历史）")
    s.add_argument("--host", default="127.0.0.1",
                   help="监听地址（默认 127.0.0.1；可指定 Tailscale IP 供 Tailnet 访问）")
    s.add_argument("--port", type=int, default=8765)
    s.add_argument("--no-open", action="store_true", dest="no_open")
    s.set_defaults(func=cmd_ui)

    s = sub.add_parser("list", help="列出所有项目")
    s.set_defaults(func=cmd_list)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
