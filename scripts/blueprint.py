"""GEO 建设蓝图：回答客户最关心的两个问题——**在哪些平台建、建什么内容**。

渠道优先级不是拍脑袋排的，是 CN-GEO 数据集 187,818 条去重引用实算出来的：
每个渠道带着全国引用量、平均引用位置、覆盖平台端数，以及"不做会怎样"。

产出 `blueprint.json`：
  channels   渠道矩阵：建什么形态的内容、多少量、什么节奏、谁做、现在覆盖了没
  contents   内容矩阵：每个目标问题需要什么类型的内容承接、现在有没有
  coverage   覆盖度：渠道覆盖率、问题承接率
  roadmap    30/60/90 分批
"""

from __future__ import annotations

import re
from pathlib import Path

import geolib as G

# ---------------------------------------------------------------- 渠道库
# national / position / platforms 均来自 references/cn-source-ranking.md 的实算值。
# position 越小 = 在 AI 答案里出现得越靠前。None 表示该数据集中样本不足。

CHANNELS_CN = [
    dict(id="official", name="官网", kind="自有阵地", domains=[], national=2569, position=None,
         platforms=None, priority="P0",
         why="品牌官网类信源只占国内全库引用的 1.37%——它是**事实源**不是引用源。"
             "作用是让 AI 描述你时口径正确、被外部站引用时有可信落点。",
         forms=["定义块与首屏事实", "产品/定价/案例页", "FAQ（答案须在静态 HTML 可见）",
                "llms.txt", "JSON-LD 结构化数据"],
         volume="核心页 8–15 个", cadence="一次建好 + 季度维护", owner="开发 + 内容",
         effect="纠正 AI 对品牌的描述口径；不指望它带来引用量"),
    dict(id="baike", name="百度百科 / 搜狗百科", kind="百科", domains=["baike.baidu.com"],
         national=9396, position=None, platforms=9, priority="P0",
         why="实体消歧的地基。baidu.com 同时是**百度 AI 37.7%、文心 29.0%** 引用的来源，一举两得。",
         forms=["品牌词条", "产品词条", "名称消歧段落"],
         volume="1–2 个词条", cadence="一次建好 + 半年维护", owner="市场",
         effect="修正品牌归类；成为多平台的共同事实源"),
    dict(id="ranking", name="榜单/品牌库站（买购网 chinapp cnpp 排行榜123）", kind="榜单",
         domains=["maigoo.com", "chinapp.com", "cnpp.cn", "phb123.com", "cnpp100.com"],
         national=17116, position=6.3, platforms=11, priority="P1",
         why="**仅 28 个域名吃掉全库引用的 9.1%，且平均引用位置全库最靠前**（cnpp 6.10、maigoo 6.36）。"
             "AI 回答「有哪些/哪个好/怎么选」时最省事就是抄一份现成榜单——而这正是大多数商业问题的问法。"
             "覆盖全部 11 个平台端，一次投入全平台受益。",
         forms=["品牌条目（长/中/短三版）", "品类榜单收录", "参数对比表"],
         volume="4–5 个站点条目", cadence="一次提交 + 季度更新", owner="市场",
         effect="国内 GEO 里性价比最高、也最常被忽略的一块"),
    dict(id="wechat", name="微信公众号 / 腾讯新闻", kind="内容平台", domains=["qq.com", "mp.weixin.qq.com"],
         national=11017, position=None, platforms=11, priority="P1",
         why="qq.com 覆盖全部 11 个平台端，且是**腾讯元宝 20.5%** 引用的来源——元宝几乎唯一的护城河。",
         forms=["深度长文（1500 字+）", "行业观点", "案例复盘"],
         volume="每月 2–4 篇", cadence="每周或每两周", owner="内容",
         effect="打通微信生态与元宝；同时覆盖微信搜一搜"),
    dict(id="toutiao", name="今日头条号 / 抖音图文", kind="内容平台",
         domains=["toutiao.com", "iesdouyin.com"], national=20956, position=None, platforms=11,
         priority="P1",
         why="toutiao.com 覆盖 11 个平台端；iesdouyin.com 是**豆包 App 28.1%** 引用的来源。"
             "抖音 AI 更是只引用自家一个域名。",
         forms=["图文（口语化标题）", "短视频 + 字幕", "行业科普"],
         volume="每月 3–5 条", cadence="每周", owner="内容",
         effect="字节生态是豆包系的硬门槛，不进去基本没戏"),
    dict(id="zhihu", name="知乎", kind="知识社区", domains=["zhihu.com", "zhuanlan.zhihu.com"],
         national=None, position=None, platforms=None, priority="P1",
         why="长期被反复引用的高质量问答源，也是 B2B 决策者的聚集地。本项目首期采样中被引 13 次。",
         forms=["回答具体问题（先结论后论证）", "专栏长文"],
         volume="每月 2–4 篇", cadence="每两周", owner="内容",
         effect="承接「哪个好/怎么选」类问题，克制植入"),
    dict(id="tech", name="CSDN / 博客园 / 腾讯云开发者社区", kind="技术社区",
         domains=["csdn.net", "blog.csdn.net", "cnblogs.com", "cloud.tencent.com"],
         national=1388, position=7.53, platforms=11, priority="P1",
         why="技术类 B2B 产品的高权重信源。csdn.net 引用位置 7.53 靠前；"
             "cnblogs.com 覆盖 11 个平台端，且是 Kimi 的第二大信源（9.1%）。"
             "本项目首期采样中 CSDN 被引 17 次、腾讯云 10 次，是实测第一梯队。",
         forms=["技术实现文章", "选型对比", "踩坑记录"],
         volume="每月 2–4 篇", cadence="每两周", owner="内容 + 技术",
         effect="技术决策者路径；对 DeepSeek、Kimi 权重高"),
    dict(id="quark", name="夸克 / 神马搜索收录", kind="搜索代理", domains=["sm.cn", "uc.cn"],
         national=6990, position=5.31, platforms=6, priority="P1",
         why="**sm.cn 是全库平均引用位置最靠前的域名（5.31），也是千问 19.2% 引用的来源。**"
             "提交收录成本极低，但几乎没人做——这是当前最明显的信息差。",
         forms=["站点收录提交", "sitemap 推送"],
         volume="一次性", cadence="一次 + 新页面时补提", owner="开发",
         effect="优化夸克收录 ≈ 优化千问，性价比极高"),
    dict(id="baijia", name="百家号 / 百度知道", kind="平台生态", domains=["baijiahao.baidu.com"],
         national=9396, position=None, platforms=9, priority="P2",
         why="百度 AI（Top8 集中度 66.2%）和文心（66.8%）都高度封闭在百度生态内，不进去基本进不了这两个平台。",
         forms=["百家号文章", "百度知道问答"],
         volume="每月 2–3 篇", cadence="每两周", owner="内容",
         effect="百度系专属通道"),
    dict(id="media", name="行业垂类媒体 / 研究机构", kind="媒体",
         domains=["36kr.com", "zol.com.cn", "askci.com", "iimedia.cn", "sohu.com", "163.com"],
         national=14733, position=6.8, platforms=11, priority="P2",
         why="综合新闻媒体占全库引用 13.6%；行业研究站（askci 6.27、iimedia 7.27）引用位置很靠前。",
         forms=["新闻稿", "行业观点投稿", "研究数据引用"],
         volume="每季 1–2 篇", cadence="按节奏", owner="市场",
         effect="权威度背书；时效性衰减快，不适合做常青内容"),
    dict(id="bilibili", name="B站 / 视频号", kind="视频", domains=["bilibili.com"],
         national=None, position=None, platforms=11, priority="P2",
         why="视频内容在多平台被引用，且豆包/抖音 AI 对视频生态权重高。首期采样中被引 3 次。",
         forms=["产品演示视频", "教程视频（带完整字幕）"],
         volume="每月 1–2 条", cadence="每月", owner="内容",
         effect="字幕是关键——AI 读的是字幕不是画面"),
]

CHANNELS_GLOBAL = [
    dict(id="official_en", name="英文官网", kind="自有阵地", domains=[], national=None, position=None,
         platforms=None, priority="P0",
         why="海外 AI 引用的可识别语言里英文占 **82.90%–95.07%**，可识别国家里 US 占 82.70%–86.76%。"
             "机翻页几乎进不了候选池，必须英文原生。",
         forms=["英文原生产品/定价/对比页", "英文 FAQ", "llms.en.txt"],
         volume="核心页 8+ 个", cadence="一次建好 + 季度维护", owner="内容 + 开发",
         effect="海外的入场门票，不是可选项"),
    dict(id="wikipedia", name="Wikipedia", kind="百科", domains=["wikipedia.org"], national=None,
         position=None, platforms=None, priority="P1",
         why="实体消歧的地基，规则严但一旦进去长期有效，被各平台反复引用。",
         forms=["英文词条（需第三方来源支撑）"], volume="1 个词条",
         cadence="一次建好", owner="市场", effect="长期权威锚点"),
    dict(id="review", name="G2 / Capterra / Product Hunt", kind="评测聚合", domains=["g2.com", "capterra.com"],
         national=None, position=None, platforms=None, priority="P1",
         why="B2B 软件类几乎必备。AI 回答 best/alternatives 类问题时高频引用评测聚合站。",
         forms=["产品页", "真实用户评价", "品类对比"],
         volume="3–4 个平台", cadence="一次建好 + 持续收评价", owner="市场",
         effect="承接 best / alternatives / vs 类问题"),
    dict(id="reddit", name="Reddit / Hacker News", kind="社区", domains=["reddit.com"], national=None,
         position=None, platforms=None, priority="P1",
         why="社区讨论被大量引用。本项目首期采样中 reddit.com 被引 4 次。",
         forms=["真实参与讨论", "AMA"], volume="持续参与", cadence="每周",
         owner="产品 + 市场",
         effect="**绝对不要刷**——被识破反噬极大，社区记忆很长"),
    dict(id="youtube", name="YouTube", kind="视频", domains=["youtube.com"], national=None,
         position=None, platforms=None, priority="P1",
         why="本项目首期海外采样中 **youtube.com 是被引最多的域名（7 次）**。",
         forms=["产品演示", "教程", "对比评测（须带英文字幕）"],
         volume="每月 1–2 条", cadence="每月", owner="内容",
         effect="海外实测第一信源"),
    dict(id="devsite", name="GitHub / 技术文档站 / dev.to", kind="技术社区",
         domains=["github.com", "dev.to", "huggingface.co"], national=None, position=None,
         platforms=None, priority="P2",
         why="技术类产品的高权重信源，首期采样中 dev.to、huggingface.co 均被引用。",
         forms=["开源组件", "技术文档", "技术博客"], volume="按能力",
         cadence="持续", owner="技术", effect="技术可信度背书"),
    dict(id="media_en", name="英文行业媒体（TechCrunch / VentureBeat / 垂类）", kind="媒体",
         domains=["techcrunch.com", "venturebeat.com"], national=None, position=None,
         platforms=None, priority="P2",
         why="三平台对来源类型高度集中：官网+新闻+行业垂类合计占 79.12%–87.52%。",
         forms=["新闻稿", "专栏投稿"], volume="每季 1–2 篇", cadence="按节奏",
         owner="市场", effect="权威度门槛（被引来源 DR 中位数 526–592）"),
    dict(id="linkedin", name="LinkedIn", kind="社交", domains=["linkedin.com"], national=None,
         position=None, platforms=None, priority="P2",
         why="首期采样中被引 3 次；B2B 决策者聚集地。",
         forms=["公司页", "创始人长文"], volume="每月 2–4 条", cadence="每周",
         owner="市场", effect="补充信源"),
]


# 阵地 id → 适配的问题组（内容↔渠道关联的口径来源）。
# 官网是所有内容的“家”，全组适配；其余阵地按其内容形态选择性承接；
# quark 是收录型基础设施，不承接具体内容。
CHANNEL_FITS = {
    "official": ["推荐", "比较", "替代", "价格", "风险", "品牌验证", "场景"],
    "baike": ["品牌验证"],
    "ranking": ["推荐", "比较", "替代"],
    "wechat": ["场景", "推荐", "风险"],
    "toutiao": ["场景", "推荐"],
    "zhihu": ["推荐", "比较", "替代", "风险"],
    "tech": ["场景", "比较", "风险"],
    "quark": [],
    "baijia": ["推荐", "场景", "品牌验证"],
    "media": ["推荐", "品牌验证"],
    "bilibili": ["场景"],
    "official_en": ["推荐", "比较", "替代", "价格", "风险", "品牌验证", "场景"],
    "wikipedia": ["品牌验证"],
    "review": ["推荐", "比较", "替代"],
    "reddit": ["推荐", "替代", "风险"],
    "youtube": ["场景", "比较"],
    "devsite": ["场景", "风险"],
    "media_en": ["推荐", "品牌验证"],
    "linkedin": ["品牌验证", "场景"],
}


# ---------------------------------------------------------------- 内容矩阵

# 问题分组 → 需要什么形态的内容承接（依据 content-patterns.md）
GROUP_PLAN = {
    "推荐": ("榜单/品类页", "承接「有哪些/best」——必须先写评选方法再给榜单，否则 AI 视为软文"),
    "比较": ("对比页", "同口径维度 6–10 个，**必须写自己的局限**，只夸自己可信度极低"),
    "替代": ("对比页", "承接「XX 的替代方案」，正面回应为什么不用现有方案"),
    "价格": ("定义/说明页", "价格透明度直接影响可信度；有特殊币种或计费方式要单独解释"),
    "风险": ("定义/说明页", "正面回应质疑（数据安全、可靠性），回避反而降低可信度"),
    "品牌验证": ("关于页 + 百科", "AI 回答「是家什么公司」时的事实源，实体消歧的主战场"),
    "场景": ("教程/how-to 页", "含数字 +61.6%、how-to +41.2% 影响力；步骤块是必需项"),
}


def _existing_content(slug: str) -> dict[str, list[str]]:
    """扫 content/ 与 assets/，看每个问题有没有内容承接。约定：文件头注释里写 `目标问题 qXXX`。"""
    pdir = G.project_dir(slug)
    hit: dict[str, list[str]] = {}
    for d, tag in ((pdir / "content", "已成稿"), (pdir / "assets" / "drafts", "AI初稿"),
                   (pdir / "assets" / "outlines", "仅大纲")):
        if not d.exists():
            continue
        for f in d.glob("*.md"):
            head = f.read_text("utf-8", "replace")[:600]
            for qid in re.findall(r"\bq\d{3}\b", head + f.stem):
                hit.setdefault(qid, []).append(tag)
    return hit


def build(slug: str) -> dict:
    cfg = G.load_config(slug)
    pdir = G.project_dir(slug)
    market = cfg.get("market", "cn")

    # 本期采样实际引用到的域名 → 判断渠道是否已覆盖
    files = sorted((pdir / "metrics").glob("*.json")) if (pdir / "metrics").exists() else []
    metrics = G.read_json(files[-1], {}) if files else {}
    cited: dict[str, set] = {"cn": set(), "global": set()}
    for m in (metrics.get("platforms") or {}).values():
        mk = m.get("market", "cn")
        for d in (m.get("top_cited_domains") or {}):
            cited[mk].add(d.lower())

    def covered(ch, mk):
        if ch["id"] in ("official", "official_en"):
            own = cfg["brand"]["site"].split("//")[-1].split("/")[0].removeprefix("www.")
            return any(d == own or d.endswith("." + own) for d in cited[mk])
        return any(any(c == dom or c.endswith("." + dom) for c in cited[mk])
                   for dom in ch["domains"])

    channels = []
    for mk, lst in (("cn", CHANNELS_CN), ("global", CHANNELS_GLOBAL)):
        if market not in (mk, "both"):
            continue
        for ch in lst:
            channels.append({**ch, "market": mk, "covered": covered(ch, mk),
                             "fits": CHANNEL_FITS.get(ch["id"], [])})

    # 内容矩阵
    hits = _existing_content(slug)
    contents = []
    for q in cfg.get("questions", []):
        form, note = GROUP_PLAN.get(q.get("group", ""), ("定义/说明页", ""))
        st = hits.get(q.get("id"), [])
        status = "已成稿" if "已成稿" in st else "AI初稿" if "AI初稿" in st else "仅大纲" if st else "缺口"
        contents.append({"id": q.get("id"), "market": q.get("market", market),
                         "group": q.get("group", ""), "question": q.get("text", ""),
                         "form": form, "note": note, "status": status})

    def rate(items, ok):
        return round(sum(1 for x in items if ok(x)) / len(items), 3) if items else 0

    coverage = {
        "channel_total": len(channels),
        "channel_covered": sum(1 for c in channels if c["covered"]),
        "channel_rate": rate(channels, lambda c: c["covered"]),
        "p0p1_total": sum(1 for c in channels if c["priority"] in ("P0", "P1")),
        "p0p1_covered": sum(1 for c in channels if c["priority"] in ("P0", "P1") and c["covered"]),
        "content_total": len(contents),
        "content_done": sum(1 for c in contents if c["status"] == "已成稿"),
        "content_rate": rate(contents, lambda c: c["status"] == "已成稿"),
        "content_gap": sum(1 for c in contents if c["status"] == "缺口"),
    }

    roadmap = [
        {"window": "0–30 天", "focus": "地基",
         "items": [c["name"] for c in channels if c["priority"] == "P0"] +
                  ["承接品牌验证与价格类问题的页面"]},
        {"window": "30–60 天", "focus": "高杠杆渠道 + 内容矩阵",
         "items": [c["name"] for c in channels if c["priority"] == "P1"][:6] +
                  ["推荐/比较/替代类内容各 1–2 篇"]},
        {"window": "60–90 天", "focus": "扩量与闭环",
         "items": [c["name"] for c in channels if c["priority"] == "P2"][:5] +
                  ["场景/风险类内容补齐", "监测跑满 6 期并复盘"]},
    ]

    data = {"slug": slug, "generated_at": G.now_iso(), "market": market,
            "channels": channels, "contents": contents,
            "coverage": coverage, "roadmap": roadmap}
    G.write_json(pdir / "blueprint.json", data)
    G.info(f"建设蓝图：{coverage['channel_covered']}/{coverage['channel_total']} 渠道已覆盖，"
           f"内容 {coverage['content_done']}/{coverage['content_total']} 已成稿 → blueprint.json")
    return data
