"""客户交付包：把一期的全部产出打成可以直接发给客户的目录。

    work/<slug>/delivery/<日期>/
      index.html            交付总览（客户先看这个）
      01-诊断报告.html/.md   本期体检 + AI 可见性
      02-执行方案.md         30/60/90 方案
      03-工单表.html/.csv    可分派、可验收、带负责角色
      04-验收表.html         上一期工单的自动验收结果
      assets/               llms.txt / JSON-LD / HTML 片段 / 内容大纲与初稿
      README.md             交付说明与下一期安排

面向客户，所以：不出现内部脚本名和调试信息，术语解释清楚，
每个结论都写清依据，不承诺任何平台一定会引用。
"""

from __future__ import annotations

import csv
import html
import json
import shutil
from pathlib import Path

import geolib as G
import report as R
import tasks as T

STATUS_CN = {"todo": "待开始", "doing": "进行中", "done": "已完成",
             "blocked": "受阻", "wontfix": "不做"}
PRI_NOTE = {"P0": "阻塞项，不做后面全白做", "P1": "主要收益来源", "P2": "长尾与扩量"}


def _tasks_table_md(data: dict, market: str | None = None) -> str:
    rows = [t for t in data.get("tasks", []) if not market or t["market"] in (market, "both")]
    if not rows:
        return "_本市场暂无工单_\n"
    L = ["| 编号 | 优先级 | 工作包 | 任务 | 负责 | 工作量 | 窗口 | 验收标准 | 状态 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(rows, key=lambda x: (x["priority"], x["package"])):
        L.append(f"| {t['id']} | {t['priority']} | {t['package']} | {R.cell(t['title'])} | "
                 f"{t['owner']} | {T.EFFORT.get(t['effort'], t['effort'])} | {t['window']} | "
                 f"{R.cell(t['acceptance'].get('desc',''))} | {STATUS_CN.get(t['status'], t['status'])} |")
    return "\n".join(L)


def _tasks_csv(data: dict, path: Path):
    def traditional(row):
        return [G.to_zh_tw(v) if isinstance(v, str) else v for v in row]

    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(traditional(["编号", "优先级", "工作包", "市场", "任务", "为什么要做", "具体动作",
                                "负责角色", "工作量", "时间窗口", "验收标准", "验收方式", "状态", "影响页面数"]))
        for t in sorted(data.get("tasks", []), key=lambda x: (x["priority"], x["package"])):
            w.writerow(traditional([
                t["id"], t["priority"], t["package"], t["market"], t["title"], t["why"],
                t["action"], t["owner"], T.EFFORT.get(t["effort"], t["effort"]), t["window"],
                t["acceptance"].get("desc", ""),
                "自动" if t["acceptance"].get("type") == "auto" else "人工",
                STATUS_CN.get(t["status"], t["status"]), len(t.get("affected", [])),
            ]))


def _overview_md(cfg, audit, metrics, data, verify_report, notes=None) -> str:
    b = cfg["brand"]
    s = data.get("summary", {})
    mk = {"cn": "国内", "global": "海外", "both": "国内 + 海外"}.get(cfg.get("market"), cfg.get("market"))
    L = [f"# {b['name']} · GEO 服务交付 · {G.today()}", "",
         f"- 服务范围：**{mk}** AI 搜索可见性",
         f"- 官网：{b['site']}",
         f"- 本期抓取：{audit.get('page_count')} 页，站点均分 **{audit.get('avg_score')}**",
         ""]
    if metrics:
        L.append(f"- AI 答案采样：{metrics.get('sample_count')} 条（{metrics.get('date')}），"
                 f"覆盖 {len(metrics.get('platforms', {}))} 个平台端")
    L += ["", "## 本期交付物", "",
          "| 文件 | 内容 |", "|---|---|",
          "| `01-诊断报告.html` | 站点技术底座、页面逐项体检、AI 答案可见性、与全国大盘对照 |",
          "| `02-执行方案.md` | 30/60/90 天路线、六个工作包、资源取舍建议 |",
          "| `03-工单表.html` / `.csv` | 可直接分派的任务，含负责角色、工作量、验收标准 |",
          "| `04-验收表.html` | 上一期工单的自动验收结果（做没做完不靠口头确认） |",
          "| `05-初稿风险清单.html` | AI 初稿里需人工核实的内容（有初稿时才有此项） |",
          "| `06-建设地图.html` | **在哪些平台建设、建什么内容、当前覆盖度** |",
          "| `assets/` | 可直接部署的资产：llms.txt、JSON-LD、HTML 片段、内容大纲与初稿 |",
          "", "## 工单概览", "",
          f"- 总数 **{s.get('total', 0)}** 条，其中可**自动验收** {s.get('auto_verifiable', 0)} 条",
          f"- 优先级：P0 {s.get('by_priority', {}).get('P0', 0)}（{PRI_NOTE['P0']}）／"
          f"P1 {s.get('by_priority', {}).get('P1', 0)}（{PRI_NOTE['P1']}）／"
          f"P2 {s.get('by_priority', {}).get('P2', 0)}（{PRI_NOTE['P2']}）",
          f"- 进度：" + "、".join(f"{STATUS_CN[k]} {v}" for k, v in s.get("by_status", {}).items() if v),
          ""]
    if s.get("by_package"):
        L += ["按工作包分布：", ""]
        L += [f"- {k}：{v} 条" for k, v in s["by_package"].items()]
        L.append("")
    if verify_report:
        p = sum(1 for r in verify_report["results"] if r["verdict"] == "通过")
        f_ = sum(1 for r in verify_report["results"] if r["verdict"] == "未达标")
        m_ = sum(1 for r in verify_report["results"] if r["verdict"] == "待人工")
        L += ["## 上期验收", "",
              f"自动验收：**通过 {p}** ／ 未达标 {f_} ／ 需人工确认 {m_}", ""]
    if notes:
        L += ["## 本期数据口径说明", ""]
        L += [f"- {n}" for n in notes]
        L.append("")
    L += ["## 怎么用这份交付", "",
          "1. 先看 `01-诊断报告.html` 的「结论先行」和「本期待办」两节",
          "2. 把 `03-工单表.csv` 导入你们的项目管理工具，按负责角色分派",
          "3. `assets/` 里的文件可以直接交给开发部署（llms.txt、JSON-LD、HTML 片段）",
          "4. `assets/outlines/` 是内容大纲，交给内容团队按骨架写；`assets/drafts/` 是 AI 初稿，"
          "**必须先按 `05-初稿风险清单` 逐条核实后才能发布**——AI 会为了填满表格而编造竞品名和参数",
          "5. 下一期我们会重跑体检与采样，自动验收哪些工单真的达标了",
          "", "## 服务边界", "",
          "- GEO 提升的是**被引用的概率**，不承诺任何平台一定会引用某个页面",
          "- 所有品牌事实、客户案例、价格与资质都必须有来源；无法核实的一律标注「待确认」，我们不会代为编造",
          "- AI 答案采样存在天然波动，单期指标变化需结合基线窗口与对照组解读，默认只作「观察相关」而非因果结论",
          "- 采样遵守各平台服务条款，不做批量滥采、不模拟登录",
          ""]
    return "\n".join(L)


def _readme(cfg, data, notes=None) -> str:
    b = cfg["brand"]
    extra = ""
    if notes:
        extra = "\n## 本期数据口径说明\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    return f"""# 交付说明

本目录是 **{b['name']}** 的 GEO（生成式引擎优化）服务第 {G.today()} 期交付。
{extra}
## 目录结构

```
index.html            ← 先看这个
01-诊断报告.html/.md
02-执行方案.md
03-工单表.html/.csv
04-验收表.html
assets/
  llms.txt            部署到网站根目录
  llms.en.txt         英文版（面向海外 AI）
  jsonld/             按页面类型贴进 <head>
  snippets/           定义块与 FAQ 块的 HTML
  outlines/           每个目标问题一份内容大纲
  drafts/             AI 初稿（需人工核实）
```

## 部署顺序建议

1. **先做 P0**：这些是「门票问题」，不解决的话后面所有内容投入都收不到效果
2. `assets/llms.txt` → 传到 `{b['site'].rstrip('/')}/llms.txt`
3. `assets/jsonld/*.json` → 按页面类型贴进对应页面的 `<head>`，注意把 `<填…>` 占位替换掉
4. `assets/snippets/definition.*.html` → 首屏口号下方（口号保留，不影响转化）
5. `assets/snippets/faq.*.html` → **注意答案必须在静态 HTML 里可见**，不要用纯 JS 折叠

## 下一期

重跑体检与采样后会自动验收工单。建议节奏：**页面体检每周，AI 答案采样每两周**。
采样过密看不出信号（指标本身有噪声），过疏则发现问题太晚。

## 一致性纪律

品牌的一句话定义必须在这四处**逐字一致**：官网首屏、关于页、JSON-LD `description`、`llms.txt`。
不一致是 AI 描述品牌出现漂移的头号原因。
"""


def run(slug: str) -> Path:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    audit = G.read_json(pdir / "audit.json", {})
    if not audit:
        G.die("缺 audit.json，先跑一次 cycle")
    data = T.load(slug)
    if not data.get("tasks"):
        G.die("还没有工单，先运行：python3 scripts/geo.py plan --slug " + slug)

    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], None) if files else None
    import verify as V
    vfiles = sorted((pdir / "verify").glob("*.json"), key=V.report_key) \
        if (pdir / "verify").exists() else []
    vrep = G.read_json(vfiles[-1], None) if vfiles else None

    # 本期体检日期：报告与验收的日期口径都以它为准
    audit_date = str(audit.get("audited_at", ""))[:10]
    notes = []  # 交付包口径说明：日期不一致必须显式标注，不能静默混入

    # 验收日期早于本期体检日期（或没有验收记录）视为「本期未验收」
    vrep_date = str(vrep.get("verified_at", ""))[:10] if vrep else ""
    unverified = not vrep or bool(audit_date and vrep_date < audit_date)
    if unverified:
        notes.append("本期未验收：" + ("尚无验收记录" if not vrep else
                     f"最近验收日期 {vrep_date}，早于本期体检日期 {audit_date}"))

    out = pdir / "delivery" / G.today()
    # 当日目录整体重建：04/05/06 是条件生成的，只增量写会让上次生成的旧文件残留
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True, exist_ok=True)

    # 01 诊断报告：报告目录日期必须与本期体检日期一致。
    # 今天有体检但报告是旧的，先补跑一次报告；仍不一致则在 README/总览里标注。
    reports = sorted((pdir / "reports").glob("2*")) if (pdir / "reports").exists() else []
    if audit_date and audit_date == G.today() and (not reports or reports[-1].name != audit_date):
        try:
            R.run(slug)
            reports = sorted((pdir / "reports").glob("2*"))
        except Exception as e:  # noqa: BLE001
            G.info(f"补跑诊断报告失败：{e}")
    if reports:
        latest = reports[-1]
        if audit_date and latest.name != audit_date:
            notes.append(f"诊断报告日期 {latest.name}，本期体检日期 {audit_date}，"
                         f"报告内容基于 {latest.name} 的数据")
        for src, dst in ((latest / "report.html", "01-診斷報告.html"),
                         (latest / "report.md", "01-診斷報告.md")):
            if src.exists():
                G.write_document(out / dst, src.read_text("utf-8"))

    # 02 执行方案
    plan = pdir / "plan.md"
    if plan.exists():
        G.write_document(out / "02-執行方案.md", plan.read_text("utf-8"))

    # 03 工单表
    mk = cfg.get("market", "cn")
    md = [f"# {cfg['brand']['name']} · GEO 执行工单 · {G.today()}", "",
          "每条工单都有负责角色和验收标准。标「自动」的验收项由系统重抓后判定，不靠口头确认。", ""]
    if mk == "both":
        md += ["## 国内市场 + 通用", "", _tasks_table_md(data, "cn"), "",
               "## 海外市场", "", _tasks_table_md(data, "global"), ""]
    else:
        md += [_tasks_table_md(data), ""]
    md += ["## 工单明细", ""]
    for t in sorted(data["tasks"], key=lambda x: (x["priority"], x["package"])):
        md += [f"### {t['id']} · {t['title']}", "",
               f"- 优先级 **{t['priority']}** ｜ 工作包 {t['package']} ｜ 市场 {t['market']} ｜ "
               f"负责 {t['owner']} ｜ 工作量 {T.EFFORT.get(t['effort'], t['effort'])} ｜ 窗口 {t['window']}",
               f"- **为什么要做**：{t['why']}",
               f"- **具体动作**：{t['action']}",
               f"- **验收标准**（{'自动' if t['acceptance'].get('type')=='auto' else '人工'}）：{t['acceptance'].get('desc','')}",
               f"- 当前状态：{STATUS_CN.get(t['status'], t['status'])}"]
        if t.get("affected"):
            md.append(f"- 影响 {len(t['affected'])} 个页面，前 3 个："
                      + "、".join(t["affected"][:3]))
        md.append("")
    tasks_md = "\n".join(md)
    G.write_document(out / "03-工單表.md", tasks_md)
    G.write_document(out / "03-工單表.html",
        R.build_html(f"{cfg['brand']['name']} GEO 工单表", tasks_md,
                     [("工单总数", str(data["summary"]["total"])),
                      ("P0", str(data["summary"]["by_priority"]["P0"])),
                      ("可自动验收", str(data["summary"]["auto_verifiable"])),
                      ("已完成", str(data["summary"]["by_status"].get("done", 0)))]))
    _tasks_csv(data, out / "03-工單表.csv")

    # 04 验收表：本期未验收时写明原因，不静默复用旧验收结果
    if vrep and not unverified:
        vm = [f"# 工单验收表 · {vrep['verified_at'][:10]}", "",
              f"重抓后站点均分 **{vrep.get('audit_avg_score')}**；本次状态变更 {vrep.get('changed')} 条。", "",
              "| 编号 | 任务 | 优先级 | 验收结论 | 依据 |", "|---|---|---|---|---|"]
        for r in vrep["results"]:
            vm.append(f"| {r['id']} | {R.cell(r['title'])} | {r['priority']} | "
                      f"{r['verdict']} | {R.cell(r['note'])} |")
        vm += ["", "> 「待人工」表示该项无法由程序判定（例如词条是否通过审核），需要人工确认后手动标记完成。", ""]
        vmd = "\n".join(vm)
        G.write_document(out / "04-驗收表.md", vmd)
        G.write_document(out / "04-驗收表.html",
            R.build_html(f"{cfg['brand']['name']} 工单验收表", vmd,
                         [("通过", str(sum(1 for r in vrep["results"] if r["verdict"] == "通过"))),
                          ("未达标", str(sum(1 for r in vrep["results"] if r["verdict"] == "未达标"))),
                          ("待人工", str(sum(1 for r in vrep["results"] if r["verdict"] == "待人工")))]))
    else:
        reason = "尚无验收记录" if not vrep else \
            f"最近一次验收日期为 {vrep_date}，早于本期体检日期 {audit_date or '未知'}"
        vmd = "\n".join([
            f"# 工单验收表 · {G.today()}", "",
            f"**本期未验收**：{reason}。", "",
            "验收需在本期体检之后重抓判定；本包不展示旧验收结果，以免与本期数据混淆。", ""])
        G.write_document(out / "04-驗收表.md", vmd)
        G.write_document(out / "04-驗收表.html",
            R.build_html(f"{cfg['brand']['name']} 工单验收表", vmd,
                         [("状态", "本期未验收")]))

    # 05 初稿风险清单：编造内容进客户交付包是最严重的事故，必须显式列出
    lint = G.read_json(pdir / "assets" / "drafts" / "_lint.json", None)
    if lint and lint.get("total_issues"):
        lm = [f"# AI 初稿风险清单 · {G.today()}", "",
              f"本期共生成 {len(lint['files'])} 份 AI 初稿，自动检查出 **{lint['total_issues']} 项**需人工核实的内容，"
              f"其中**高风险 {lint['high']} 项**。", "",
              "> **这些初稿在核实完成前不得发布。** AI 会为了把表格填满而编造竞品名、",
              "> 竞品参数和市场数据——这类内容一旦发出去，损害的是品牌可信度，",
              "> 而可信度正是 GEO 的全部基础。", "",
              "| 文件 | 风险等级 | 类型 | 说明 | 原文片段 |", "|---|---|---|---|---|"]
        for fn, issues in lint["files"].items():
            for i in issues:
                lm.append(f"| `{fn}` | {i['level']} | {i['type']} | {R.cell(i['detail'])} | {R.cell(i['excerpt'][:60])} |")
        lm += ["", "## 处理方式", "",
               "- **高风险**：直接删除或替换成真实信息。占位竞品名一律删掉",
               "- **中风险（未核实数字）**：能核实的补上来源与核验日期；不能核实的删掉或改写成「待补」",
               "- **低风险（年份）**：统一改成当前年份", ""]
        lmd = "\n".join(lm)
        G.write_document(out / "05-初稿風險清單.md", lmd)
        G.write_document(out / "05-初稿風險清單.html",
            R.build_html(f"{cfg['brand']['name']} AI 初稿风险清单", lmd,
                         [("初稿数", str(len(lint["files"]))),
                          ("待核实项", str(lint["total_issues"])),
                          ("高风险", str(lint["high"]))]))

    # 06 建设地图：客户最关心的"在哪些平台建、建什么内容"
    bp = G.read_json(pdir / "blueprint.json", None)
    if bp:
        cov = bp["coverage"]
        bm = [f"# GEO 建设地图 · {G.today()}", "",
              "回答两个问题：品牌要在**哪些平台**建设、每个平台**建什么内容**。", "",
              f"- 渠道覆盖：**{cov['channel_covered']}/{cov['channel_total']}**"
              f"（P0/P1 关键渠道 {cov['p0p1_covered']}/{cov['p0p1_total']}）",
              f"- 内容承接：**{cov['content_done']}/{cov['content_total']}** 个目标问题已有成稿", "",
              "> 渠道优先级不是主观排的——每条都带着 CN-GEO 数据集 187,818 条去重引用实算出的",
              "> 全国引用量与平均引用位置。「引用位置」越小表示在 AI 答案里出现得越靠前。", "",
              "## 一、在哪些平台建设", ""]
        for pri in ("P0", "P1", "P2"):
            rows = [c for c in bp["channels"] if c["priority"] == pri]
            if not rows:
                continue
            note = {"P0": "地基，不做后面全白做", "P1": "主要收益来源", "P2": "扩量"}[pri]
            bm += [f"### {pri} · {note}（已覆盖 {sum(1 for c in rows if c['covered'])}/{len(rows)}）", "",
                   "| 渠道 | 状态 | 建什么 | 建多少 | 节奏 | 负责 | 数据依据 |",
                   "|---|---|---|---|---|---|---|"]
            for c in rows:
                ev = []
                if c.get("national"):
                    ev.append(f"全国引用 {c['national']:,}")
                if c.get("position"):
                    ev.append(f"引用位置 {c['position']}")
                if c.get("platforms"):
                    ev.append(f"覆盖 {c['platforms']} 端")
                bm.append(f"| {R.cell(c['name'])} | {'✓ 已被引用' if c['covered'] else '缺口'} "
                          f"| {R.cell(' / '.join(c['forms']))} | {R.cell(c['volume'])} "
                          f"| {R.cell(c['cadence'])} | {c['owner']} | {'；'.join(ev) or '—'} |")
            bm.append("")
        bm += ["## 二、建设哪些内容", ""]
        by_form: dict[str, list] = {}
        for c in bp["contents"]:
            by_form.setdefault(c["form"], []).append(c)
        for form, lst in by_form.items():
            done = sum(1 for x in lst if x["status"] == "已成稿")
            bm += [f"### {form} · {len(lst)} 题（已成稿 {done}）", "",
                   f"_{lst[0]['note']}_", "",
                   "| 目标问题 | 分组 | 市场 | 状态 |", "|---|---|---|---|"]
            for c in lst:
                mk = {"cn": "国内", "global": "海外"}.get(c["market"], "通用")
                bm.append(f"| {R.cell(c['question'])} | {c['group']} | {mk} | {c['status']} |")
            bm.append("")
        bm += ["## 三、分批建设节奏", ""]
        for r in bp["roadmap"]:
            bm += [f"**{r['window']} · {r['focus']}**", ""] + [f"- {i}" for i in r["items"]] + [""]
        bm += ["---", "",
               "**一条纪律**：品牌官网类信源只占国内全库引用的 **1.37%**——官网是**事实源**不是**引用源**。",
               "把官网从 60 分做到 90 分的边际收益，远低于拿下一个榜单站词条。资源有限时优先做外部渠道。", ""]
        bmd = "\n".join(bm)
        G.write_document(out / "06-建設地圖.md", bmd)
        G.write_document(out / "06-建設地圖.html",
            R.build_html(f"{cfg['brand']['name']} GEO 建设地图", bmd,
                         [("渠道覆盖", f"{cov['channel_covered']}/{cov['channel_total']}"),
                          ("关键渠道", f"{cov['p0p1_covered']}/{cov['p0p1_total']}"),
                          ("内容承接", f"{cov['content_done']}/{cov['content_total']}"),
                          ("内容缺口", str(cov["content_gap"] + sum(
                              1 for c in bp["contents"] if c["status"] == "仅大纲")))]))

    # assets
    adir = pdir / "assets"
    if adir.exists():
        dst = out / "assets"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(adir, dst)

    # index + README
    ov = G.to_zh_tw(_overview_md(cfg, audit, metrics, data, None if unverified else vrep, notes))
    G.write_document(out / "index.md", ov)
    cards = [("站点均分", str(audit.get("avg_score"))),
             ("抓取页数", str(audit.get("page_count"))),
             ("工单总数", str(data["summary"]["total"])),
             ("P0 待办", str(sum(1 for t in data["tasks"]
                                 if t["priority"] == "P0" and t["status"] != "done")))]
    if metrics:
        rates = [m["mention_rate"] for m in metrics["platforms"].values()
                 if m.get("mention_rate") is not None]
        if rates:
            cards.append(("平均提及率", f"{sum(rates)/len(rates):.0%}"))
    G.write_document(
        out / "index.html",
        R.build_html(f"{cfg['brand']['name']} · GEO 服务交付 {G.today()}", ov, cards),
    )
    G.write_document(out / "README.md", _readme(cfg, data, notes))

    G.info(f"交付包已生成 → {out}")
    return out
