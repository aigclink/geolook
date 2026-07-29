"""行业大盘对照：把项目采样到的信源，和 CN-GEO 实测榜比一比。

数据来自 `references/cn-source-ranking.md`（CN-GEO 数据集 187,818 条去重引用实算）。
这里只内嵌结论值，不依赖 duckdb/parquet——复算方法写在那份文件末尾。

用途：报告里回答两个问题
  1. AI 在你这个行业引用的信源，和全国大盘重合吗？
  2. 大盘里的高杠杆信源（榜单站、内容平台），你一个都没占的有哪些？
"""

from __future__ import annotations

# 跨平台通吃层：CN-GEO 里覆盖全部 11 个平台端的高引用域名
CROSS_PLATFORM = {
    "qq.com": ("内容平台", "腾讯", 11017),
    "toutiao.com": ("内容平台", "字节", 9911),
    "sohu.com": ("综合新闻媒体", "搜狐", 8000),
    "maigoo.com": ("商业推荐与榜单", "买购网", 6741),
    "smzdm.com": ("兴趣与生活社区", "什么值得买", 6547),
    "163.com": ("综合新闻媒体", "网易", 4777),
    "chinapp.com": ("商业推荐与榜单", "品牌网", 3955),
    "cnpp.cn": ("商业推荐与榜单", "—", 3429),
    "ctrip.com": ("本地服务", "携程", 3273),
    "sina.cn": ("综合新闻媒体", "新浪", 3112),
    "sina.com.cn": ("综合新闻媒体", "新浪", 1951),
    "dianping.com": ("本地服务", "美团", 1895),
    "cnblogs.com": ("专业技术社区", "博客园", 1388),
    "zol.com.cn": ("科技专业内容", "中关村在线", 987),
    "36kr.com": ("商业媒体", "—", 969),
}

# 平台生态门槛：想进这个平台，这些域名是必经之路
ECOSYSTEM = {
    "baidu.com": ["百度AI 37.7%", "文心 29.0%"],
    "sm.cn": ["千问 19.2%（夸克/神马）"],
    "iesdouyin.com": ["豆包App 28.1%", "豆包web 12.0%", "抖音AI 100%"],
    "toutiao.com": ["豆包系次要入口"],
    "qq.com": ["元宝 20.5%"],
}

# 引用位置最靠前的域名（average_quote_position 越小越靠前）
TOP_POSITION = {
    "sm.cn": 5.31, "cnpp.cn": 6.10, "xnnews.com.cn": 6.25, "askci.com": 6.27,
    "maigoo.com": 6.36, "phb123.com": 7.12, "iimedia.cn": 7.27, "uc.cn": 7.32,
    "cnpp100.com": 7.35, "csdn.net": 7.53,
}

# 全库类目占比，用来解释"官网做得再好也只有 1.37%"
CATEGORY_SHARE = [
    ("内容平台（qq/toutiao/baidu/iesdouyin）", 0.164, 4),
    ("综合新闻媒体", 0.136, 68),
    ("商业推荐与榜单站", 0.091, 28),
    ("本地服务与用户内容", 0.052, 23),
    ("兴趣与生活社区", 0.038, 8),
    ("地方新闻媒体", 0.035, 55),
    ("政府机构", 0.020, 46),
    ("品牌官网 / 企业站", 0.0137, 52),
]


def _norm(domain: str) -> str:
    d = (domain or "").lower().removeprefix("www.")
    return d


def compare(cited_domains: dict[str, int]) -> dict:
    """cited_domains: {域名: 本期被引次数}（来自项目采样）"""
    got = {_norm(d): n for d, n in cited_domains.items()}

    def hit(base: str) -> int:
        """本期是否引到该域名（含子域）"""
        return sum(n for d, n in got.items() if d == base or d.endswith("." + base))

    covered, missing = [], []
    for dom, (cat, eco, cit) in sorted(CROSS_PLATFORM.items(), key=lambda x: -x[1][2]):
        n = hit(dom)
        (covered if n else missing).append({
            "domain": dom, "category": cat, "ecosystem": eco,
            "national_citations": cit, "your_citations": n,
        })

    eco_gaps = []
    for dom, notes in ECOSYSTEM.items():
        if not hit(dom):
            eco_gaps.append({"domain": dom, "why": "、".join(notes)})

    # 本期引到的、且在全国榜里位置最靠前的域名——这些是要加码的
    strong = sorted(
        ({"domain": d, "position": p, "your_citations": hit(d)} for d, p in TOP_POSITION.items() if hit(d)),
        key=lambda x: x["position"],
    )

    return {
        "cross_platform_covered": covered,
        "cross_platform_missing": missing,
        "coverage_rate": round(len(covered) / len(CROSS_PLATFORM), 3),
        "ecosystem_gaps": eco_gaps,
        "high_position_hits": strong,
        "category_share": CATEGORY_SHARE,
    }
