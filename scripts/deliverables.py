"""三份正式交付物：诊断报告 / 优化方案 / 执行方案。

前面各模块产出的是数据（audit.json / metrics / blueprint.json / tasks.json），
这里把它们组织成客户看得懂、能签收的三份文档：

  诊断报告  现在什么样   —— 站点体检 + AI 可见性 + 与全国大盘对照
  优化方案  应该改成什么样 —— 结论、机会地图、建设地图、资源取舍
  执行方案  谁在什么时候做什么 —— 工单、排期、验收标准、资产清单

三份都出 Markdown + 自包含 HTML。
"""

from __future__ import annotations

from pathlib import Path

import blueprint as BP
import geolib as G
import report as R
import tasks as T

STATUS_CN = {"todo": "待开始", "doing": "进行中", "done": "已完成",
             "blocked": "受阻", "wontfix": "不做"}


def _load(slug: str):
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    audit = G.read_json(pdir / "audit.json", {})
    mfiles = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(mfiles[-1], None) if mfiles else None
    bp = G.read_json(pdir / "blueprint.json", None)
    td = T.load(slug)
    return cfg, audit, metrics, bp, td


# ---------------------------------------------------------------- 优化方案

def optimization_plan(slug: str) -> str:
    cfg, audit, metrics, bp, td = _load(slug)
    b = cfg["brand"]
    mk = {"cn": "国内", "global": "海外", "both": "国内 + 海外"}.get(cfg.get("market"))
    L = [f"# {b['name']} · GEO 优化方案", "",
         f"编制日期 {G.today()} ｜ 服务范围 **{mk}** AI 搜索可见性 ｜ 官网 {b['site']}", "",
         "本方案回答一个问题：**现状要改成什么样，为什么。**",
         "具体谁在什么时候做什么，见配套的《GEO 执行方案》。", "",
         "---", "", "## 一、当前处在什么位置", ""]

    score = audit.get("avg_score")
    gd = audit.get("grade_distribution", {})
    ab = (gd.get("A", 0) + gd.get("B", 0))
    L += [f"- 站点均分 **{score}**（满分 100，70 分以上算「基本可用」）",
          f"- 抓取 {audit.get('page_count')} 页，其中可直接被引用或基本可用的 **{ab}** 页", ""]

    if metrics:
        for m_, name in (("cn", "国内"), ("global", "海外")):
            rows = [v for v in metrics["platforms"].values() if v.get("market", "cn") == m_]
            if not rows:
                continue
            # None = 该平台本期未测，不参与平均；全 None 显示「未测」，不编数
            mr_v = [v["mention_rate"] for v in rows if v.get("mention_rate") is not None]
            oc_v = [v["own_domain_cite_rate"] for v in rows if v.get("own_domain_cite_rate") is not None]
            mr = f"{sum(mr_v)/len(mr_v):.0%}" if mr_v else "未测"
            oc = f"{sum(oc_v)/len(oc_v):.0%}" if oc_v else "未测"
            L.append(f"- {name}市场：{len(rows)} 个平台端平均**无提示提及率 {mr}**、"
                     f"引用官网率 {oc}")
        L.append("")
        L += ["> 「无提示提及率」指问题里不出现品牌名时，AI 主动提到你的比例。",
              "> 点名提问的样本已单独归入品牌认知，不混进这个指标——否则是假阳性。", ""]

    L += ["## 二、要改什么：三个层次", "",
          "GEO 不是一件事，是三段漏斗。每一段的瓶颈不同，动作也不同。", "",
          "| 环节 | 现状判断 | 要做的事 |", "|---|---|---|"]

    site = audit.get("site", {})
    gate = []
    if site.get("ai_bots_blocked"):
        gate.append("robots 封禁了 AI 抓取器")
    if not site.get("has_sitemap"):
        gate.append("无 sitemap")
    if not site.get("has_llms_txt"):
        gate.append("无 llms.txt")
    spa = sum(1 for p in audit.get("pages", [])
              if "SPA_SHELL" in p.get("issue_codes", [])
              or (p.get("issue_codes") is None and p.get("word_count", 0) < 120))
    if spa:
        gate.append(f"{spa} 个页面静态 HTML 无正文")
    L.append(f"| ① 能不能被抓到 | {'／'.join(gate) if gate else '技术底座基本干净'} "
             f"| {'先修门票问题，这些不解决后面全白做' if gate else '维持现状即可'} |")

    own = None
    if metrics:
        vals = [v["own_domain_cite_rate"] for v in metrics["platforms"].values()
                if v.get("own_domain_cite_rate") is not None]
        own = sum(vals) / len(vals) if vals else None
    if own is None:
        L.append("| ② 会不会被选进引用 | 引用官网率 未测 "
                 "| 本期没有可见性采样，先补采样再判断，不编数 |")
    else:
        L.append(f"| ② 会不会被选进引用 | 引用官网率 {own:.0%} "
                 f"| {'官网进不了检索结果，需提交收录 + 在高频被引站点建内容' if own < 0.1 else '维持并扩大外部信源'} |")

    gaps = audit.get("block_gap", [])
    top_gap = "、".join(f"{g['block']}({g['missing_pages']}/{g['total']})" for g in gaps[:3])
    L.append(f"| ③ 会不会被吸收进答案 | 缺口最大：{top_gap or '—'} "
             f"| 补可抽取块并把核心页扩到 1000 词以上 |")
    L.append("")

    L += ["## 三、机会地图：按杠杆排序", "",
          "以下顺序不是主观排的，依据是 CN-GEO 数据集 187,818 条去重引用的实算结果。", ""]

    order = [
        ("门票问题", "P0", gate,
         "robots、sitemap、llms.txt、SPA 空壳页、结构化数据。这类问题不解决，内容投入收不到效果。"),
        ("实体消歧与事实底座", "P0", b.get("disambiguation") or [],
         "让 AI 描述品牌时口径正确。定义句必须在官网首屏、关于页、JSON-LD、llms.txt 四处逐字一致。"),
        ("可抽取块", "P1", [g["block"] for g in gaps if g["missing_pages"] >= max(3, g["total"] * .3)],
         "实测增益：含数字 +61.6%、定义 +57.3%、对比 +55.3%、how-to +41.2%。"),
        ("外部信源", "P1", [],
         "**品牌官网类信源只占国内全库引用的 1.37%**——官网是事实源不是引用源。"
         "把官网从 60 分做到 90 分的边际收益，远低于拿下一个榜单站词条。"),
        ("内容矩阵", "P1", [],
         "每个目标问题需要一种特定形态的内容承接。AI 回答不同问法时找的是不同类型的页面。"),
        ("监测闭环", "P2", [],
         "周期复跑，自动验收哪些工单真的闭环。没有闭环的优化等于没做。"),
    ]
    for name, pri, items, note in order:
        L += [f"### {pri} · {name}", "", note, ""]
        if items:
            L += [f"- {x}" for x in items[:6]] + [""]

    if bp:
        cov = bp["coverage"]
        L += ["## 四、建设地图：在哪些平台建、建什么内容", "",
              f"渠道覆盖 **{cov['channel_covered']}/{cov['channel_total']}**"
              f"（P0/P1 关键渠道 {cov['p0p1_covered']}/{cov['p0p1_total']}）；"
              f"内容承接 **{cov['content_done']}/{cov['content_total']}**。", "",
              "完整明细见《GEO 建设地图》。这里只列**最该先补的缺口**：", ""]
        miss = [c for c in bp["channels"] if not c["covered"] and c["priority"] in ("P0", "P1")]
        miss.sort(key=lambda c: (-(c.get("national") or 0)))
        if miss:
            L += ["| 渠道 | 优先级 | 建什么 | 节奏 | 数据依据 |", "|---|---|---|---|---|"]
            for c in miss[:8]:
                ev = []
                if c.get("national"):
                    ev.append(f"全国引用 {c['national']:,}")
                if c.get("position"):
                    ev.append(f"引用位置 {c['position']}")
                L.append(f"| {R.cell(c['name'])} | {c['priority']} | {R.cell(' / '.join(c['forms'][:2]))} "
                         f"| {R.cell(c['cadence'])} | {'；'.join(ev) or '—'} |")
            L.append("")

    L += ["## 五、资源取舍建议", ""]
    if cfg.get("market") == "both":
        L += ["- **人力只够打一个市场时先打国内**：国内该品类在 AI 认知里往往尚未成型，先定义者得天下；",
              "  海外品类通常已成熟，同样投入下挤进已有候选集要难得多",
              "- 英文内容**必须原生写**，不能机翻中文页——海外 AI 引用的可识别语言里英文占 82.90%–95.07%", ""]
    L += ["- **不要把预算压在官网重构上**。官网做到「可抓取 + 有定义 + 有结构化数据 + 口径统一」即可，",
          "  剩下的力气转到外部信源",
          "- 内容宁可少而深。1000 词是门槛不是目标——高影响力页面平均 1,943 词，低分页仅 170 词", "",
          "## 六、目标与验收口径", ""]
    tg = cfg.get("targets", {})
    L += ["| 指标 | 当前 | 90 天目标 |", "|---|---|---|",
          f"| 站点均分 | {score} | {tg.get('avg_page_score', 70)} |"]
    if metrics:
        for m_, name in (("cn", "国内"), ("global", "海外")):
            rows = [v for v in metrics["platforms"].values() if v.get("market", "cn") == m_]
            if rows:
                cur_v = [v["mention_rate"] for v in rows if v.get("mention_rate") is not None]
                cur = f"{sum(cur_v)/len(cur_v):.0%}" if cur_v else "未测"
                L.append(f"| {name}无提示提及率 | {cur} | {tg.get('mention_rate', .3):.0%} |")
    L += [f"| 引用官网率 | {f'{own:.0%}' if own is not None else '未测'} | {tg.get('own_domain_cite_rate', .2):.0%} |", "",
          "## 七、边界", "",
          "- GEO 提升的是**被引用的概率**，不承诺任何平台一定会引用某个页面",
          "- 所有品牌事实、客户案例、价格与资质都必须有来源；无法核实的一律标注「待确认」",
          "- AI 答案采样存在天然波动，单期变化需结合基线窗口与对照组解读，默认只作「观察相关」",
          "- 采样遵守各平台服务条款，不做批量滥采、不模拟登录", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 执行方案

def execution_plan(slug: str) -> str:
    cfg, audit, metrics, bp, td = _load(slug)
    b = cfg["brand"]
    rows = td.get("tasks", [])
    s = td.get("summary", {})
    L = [f"# {b['name']} · GEO 执行方案", "",
         f"编制日期 {G.today()} ｜ 工单 {s.get('total', 0)} 条"
         f"（其中 **{s.get('auto_verifiable', 0)} 条可由系统自动验收**）", "",
         "本方案回答：**谁、在什么时间窗口、做什么、做到什么程度算完成。**", "",
         "> 标「自动」的验收项由系统重抓站点后判定，不靠口头确认；",
         "> 做完会自动标记完成，出现回归会自动打回待开始。", "", "---", ""]

    L += ["## 一、分批排期", ""]
    for win, label in (("30天", "第一批 · 0–30 天 · 地基"),
                       ("60天", "第二批 · 30–60 天 · 主要收益"),
                       ("90天", "第三批 · 60–90 天 · 扩量与闭环")):
        batch = [t for t in rows if t.get("window") == win]
        if not batch:
            continue
        done = sum(1 for t in batch if t["status"] == "done")
        L += [f"### {label}（{done}/{len(batch)} 完成）", "",
              "| 编号 | 任务 | 工作包 | 负责 | 工作量 | 验收标准 | 状态 |",
              "|---|---|---|---|---|---|---|"]
        for t in sorted(batch, key=lambda x: x["priority"]):
            L.append(f"| {t['id']} | {R.cell(t['title'])} | {t['package']} | {t['owner']} "
                     f"| {T.EFFORT.get(t['effort'], t['effort'])} "
                     f"| {R.cell(t['acceptance'].get('desc',''))} "
                     f"| {STATUS_CN.get(t['status'], t['status'])} |")
        L.append("")

    L += ["## 二、按负责角色拆分", "",
          "把这一节直接发给对应的人，不需要读全文。", ""]
    by_owner: dict[str, list] = {}
    for t in rows:
        by_owner.setdefault(t["owner"], []).append(t)
    for owner, ts in sorted(by_owner.items(), key=lambda x: -len(x[1])):
        open_ = [t for t in ts if t["status"] != "done"]
        L += [f"### {owner}（{len(open_)} 项待办 / 共 {len(ts)} 项）", ""]
        for t in sorted(open_, key=lambda x: (x["priority"], x["window"])):
            L += [f"**{t['id']} · {t['title']}** ｜ {t['priority']} ｜ {t['window']} ｜ "
                  f"{T.EFFORT.get(t['effort'], t['effort'])}", "",
                  f"- 为什么：{t['why']}", f"- 做什么：{t['action']}",
                  f"- 验收（{'自动' if t['acceptance'].get('type') == 'auto' else '人工'}）："
                  f"{t['acceptance'].get('desc','')}"]
            if t.get("affected"):
                L.append(f"- 影响 {len(t['affected'])} 个页面，例：{t['affected'][0]}")
            L.append("")
        if not open_:
            L += ["（本角色任务已全部完成）", ""]

    adir = G.project_dir(slug) / "assets"
    if adir.exists():
        L += ["## 三、可直接使用的资产", "",
              "以下文件已生成好，开发和内容团队可以直接取用：", "",
              "| 文件 | 用途 | 谁用 |", "|---|---|---|"]
        m = [("llms.txt", "官方事实索引，传到网站根目录", "开发"),
             ("llms.en.txt", "英文版事实索引", "开发"),
             ("jsonld/*.json", "结构化数据，按页面类型贴进 `<head>`", "开发"),
             ("snippets/definition.*.html", "定义块，放首屏口号下方", "开发"),
             ("snippets/faq.*.html", "FAQ 块，答案必须在静态 HTML 里可见", "开发"),
             ("outlines/*.md", "每个目标问题一份内容大纲", "内容"),
             ("drafts/*.md", "AI 初稿，**必须过风险检查并人工核实后才能发布**", "内容"),
             ("DEPLOY.md", "部署清单，含每步验收标准", "开发")]
        for f, use, who in m:
            exists = any(adir.glob(f)) if "*" in f else (adir / f).exists()
            if exists:
                L.append(f"| `{f}` | {use} | {who} |")
        L.append("")

    L += ["## 四、验收与复跑机制", "",
          "1. 团队按工单执行，完成后在工作台标记或直接部署",
          "2. 每期重跑体检与采样，系统**自动判定**哪些工单真的闭环",
          "3. 无法程序判定的（如百科词条是否过审）标「待人工」，确认后手动标记",
          "4. 出现回归（之前达标现在不达标）会自动打回，不会被忽略", "",
          "建议节奏：**页面体检每周，AI 答案采样每两周或每月**。",
          "采样有成本且指标本身有噪声，跑太密看不出信号，跑太疏发现问题太晚。", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def run(slug: str) -> Path:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    out = pdir / "deliverables"
    out.mkdir(parents=True, exist_ok=True)
    name = cfg["brand"]["name"]

    # 诊断报告直接复用最新一期报告
    reports = sorted((pdir / "reports").glob("2*")) if (pdir / "reports").exists() else []
    if reports:
        import shutil
        for src, dst in ((reports[-1] / "report.md", "1-GEO診斷報告.md"),
                         (reports[-1] / "report.html", "1-GEO診斷報告.html")):
            if src.exists():
                shutil.copy2(src, out / dst)

    audit = G.read_json(pdir / "audit.json", {})
    td = T.load(slug)

    opt = G.to_zh_tw(optimization_plan(slug))
    G.write_document(out / "2-GEO最佳化方案.md", opt)
    G.write_document(out / "2-GEO最佳化方案.html",
        R.build_html(f"{name} · GEO 优化方案", opt,
                     [("站点均分", str(audit.get("avg_score", "—"))),
                      ("抓取页数", str(audit.get("page_count", "—"))),
                      ("工单总数", str(td.get("summary", {}).get("total", 0)))]))

    exe = G.to_zh_tw(execution_plan(slug))
    G.write_document(out / "3-GEO執行方案.md", exe)
    s = td.get("summary", {})
    G.write_document(out / "3-GEO執行方案.html",
        R.build_html(f"{name} · GEO 执行方案", exe,
                     [("工单总数", str(s.get("total", 0))),
                      ("P0", str(s.get("by_priority", {}).get("P0", 0))),
                      ("可自动验收", str(s.get("auto_verifiable", 0))),
                      ("已完成", str(s.get("by_status", {}).get("done", 0)))]))

    # 清除舊版簡體檔名，避免儀表板同時顯示兩套交付物。
    for legacy in ("1-GEO诊断报告.md", "1-GEO诊断报告.html",
                   "2-GEO优化方案.md", "2-GEO优化方案.html",
                   "3-GEO执行方案.md", "3-GEO执行方案.html"):
        (out / legacy).unlink(missing_ok=True)

    G.info(f"三份交付物已生成 → {out}")
    return out
