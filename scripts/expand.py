"""拓词：用搜索引擎下拉词把真实需求接进问题库。

方法来自经典的「词根 → 自动补全扩词」流程（Google Trends 词找词的同款思路）：
以品牌 / 品类 / 竞品为词根，拉百度下拉（国内）与 Google suggest（海外）的真实
搜索词，按线索词归入问题库既有分组，并给出可入库的问句表述。

纪律（与全站口径一致）：
- 拓词只产**候选**，入库永远由用户在界面上勾选确认——问题库跨期可比，不自动加题
- 数据源是两个公开无鉴权端点，纯 requests，不引第三方库、不需要任何 Key
- 每期快照 diff：首次出现的词标 new，作为「需求上升」信号，只作观察不作归因
"""
from __future__ import annotations

import json
import re
import time
from urllib.parse import quote

import geolib as G
import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"}

# 词根 × 修饰词。修饰词按词根类型区分：品牌/竞品考察认知与替代，品类考察选型。
MODS = {
    "cn": {
        "brand":      ["", " 怎么样", " 靠谱吗", " 替代", " 对比", " 价格"],
        "competitor": ["", " 怎么样", " 替代", " 对比", " 缺点"],
        "category":   ["", " 推荐", " 哪个好", " 对比", " 价格"],
    },
    "global": {
        "brand":      ["", " review", " alternative", " vs", " pricing"],
        "competitor": ["", " review", " alternative", " vs"],
        "category":   ["", " best", " comparison", " pricing"],
    },
}

# 线索词 → 问题库分组（与 bootstrap 的七组口径一致）
GROUP_CUES = [
    ("替代", ["替代", "平替", "alternative", "instead of", "替换"]),
    ("比较", [" vs", "对比", "比较", "区别", "哪个好", "comparison", "compare", "versus"]),
    ("价格", ["价格", "多少钱", "收费", "免费", "pricing", "price", "cost", "free"]),
    ("风险", ["靠谱", "骗", "投诉", "缺点", "坑", "scam", "safe", "problem", "缺陷"]),
    ("品牌验证", ["怎么样", "评测", "测评", "好用吗", "review", "worth it"]),
    ("推荐", ["推荐", "排行", "排名", "best", "top", "哪家"]),
]

# 模板兜底：没配 LLM Key 时把搜索词转成自然问句
TEMPLATES = {
    "cn": {
        "推荐": "{t}，有值得推荐的吗？",
        "比较": "{t}，到底该怎么选？",
        "替代": "{t}，有哪些替代方案？",
        "价格": "{t}大概是什么价位？值不值？",
        "风险": "{t}，有什么要避的坑吗？",
        "品牌验证": "{t}？用过的说说实际体验。",
        "场景": "{t}，实际用起来怎么样？",
    },
    "global": {
        "推荐": "Any recommendations for {t}?",
        "比较": "How should I choose between options for {t}?",
        "替代": "What are good alternatives for {t}?",
        "价格": "Is {t} worth the price?",
        "风险": "Any pitfalls to watch out for with {t}?",
        "品牌验证": "Is {t} actually good in practice?",
        "场景": "How does {t} work in real use?",
    },
}

STOP_BIGRAMS = {"工具", "软件", "智能", "平台", "系统", "服务", "在线", "免费",
                "是什", "什么", "怎么", "么样", "怎样", "如何", "哪个", "哪些", "没有",
                "有没", "可以", "一个", "这个", "为什", "推荐", "好用", "用吗"}


# ---------------------------------------------------------------- 下拉词源

def suggest_baidu(q: str, timeout: int = 6) -> list[str]:
    """百度下拉。公开 JSONP 端点，oe=utf-8 直接拿 UTF-8。"""
    url = f"https://suggestion.baidu.com/su?wd={quote(q)}&ie=utf-8&oe=utf-8"
    r = requests.get(url, headers=UA, timeout=timeout)
    m = re.search(r"s:(\[.*?\])", r.text)
    return json.loads(m.group(1)) if m else []


def suggest_google(q: str, hl: str = "en", timeout: int = 6) -> list[str]:
    """Google 自动补全。client=firefox 返回纯 JSON。"""
    url = (f"https://suggestqueries.google.com/complete/search"
           f"?client=firefox&hl={hl}&q={quote(q)}")
    r = requests.get(url, headers=UA, timeout=timeout)
    data = json.loads(r.text)
    return [s for s in (data[1] if len(data) > 1 else []) if isinstance(s, str)]


# ---------------------------------------------------------------- 词根与匹配

def _roots(cfg: dict) -> list[dict]:
    """词根 = 品牌（含别名）+ 竞品 + 品类词。上限 14 个，品牌与竞品优先。"""
    out, seen = [], set()

    def add(root, kind, market):
        r = (root or "").strip()
        if len(r) < 2 or r.lower() in seen:
            return
        seen.add(r.lower())
        out.append({"root": r, "kind": kind, "market": market})

    b = cfg.get("brand") or {}
    market = cfg.get("market", "cn")
    add(b.get("name"), "brand", market)
    for al in (b.get("aliases") or [])[:2]:
        add(al, "brand", market)
    for c in cfg.get("competitors") or []:
        add(c.get("name"), "competitor", c.get("market") or market)
    add(b.get("industry"), "category", market)
    for pdt in (b.get("products") or [])[:4]:
        add(pdt, "category", market)
    return out[:14]


NAV_RX = re.compile(r"下载|官网|官方网站|安装|登录|注册|入口|客户端|手机版|破解|激活|会员|app\b|"
                    r"download|install|login|sign ?in|sign ?up|app store", re.I)


def _relevant(term: str, root: str) -> bool:
    """下拉词天然会前缀漂移到无关实体（如品牌词根扩出别家品牌）。

    规则：词根含英文词元（如品牌英文名）时必须命中该词元——CJK 部分不作兜底，
    否则「AIGCLINK定制家」会漂到「ai定制家居」这类无关行业词；
    纯中文词根要求覆盖一半以上的 CJK 二元组。导航意图词（下载/官网/安装…）
    对 AI 问句没有价值，直接丢弃。"""
    if NAV_RX.search(term):
        return False
    tl = term.lower().replace(" ", "")
    latin = re.findall(r"[A-Za-z]{4,}", root.lower())
    if latin:
        return any(w in tl for w in latin)
    rb = {b for b in _bigrams(root) if re.match(r"[一-鿿]", b)}
    if not rb:
        return False
    tb = _bigrams(term)
    return len(rb & tb) * 2 >= len(rb)


def _classify(term: str, kind: str) -> str:
    low = term.lower()
    for grp, cues in GROUP_CUES:
        if any(c in low for c in cues):
            # 「怎么样/评测」对品牌与竞品是品牌验证，对品类更接近推荐
            if grp == "品牌验证" and kind == "category":
                return "推荐"
            return grp
    return "场景"


def _bigrams(s: str) -> set[str]:
    cjk = re.findall(r"[一-鿿]{2,}", s)
    out = set()
    for w in cjk:
        out.update(w[i:i + 2] for i in range(len(w) - 1))
    out.update(w.lower() for w in re.findall(r"[A-Za-z]{3,}", s))
    return out - STOP_BIGRAMS


def _match_questions(cfg: dict, terms: list[dict]) -> dict:
    """场景②：把拓词映射回问题库——按词根/词面重叠打「需求」标。

    只作展示信号（🔥 徽标 + 悬停给出依据），不改任何指标口径。"""
    demand: dict[str, dict] = {}
    for q in cfg.get("questions") or []:
        qb = _bigrams(q.get("text", ""))
        hits, roots, has_new = [], set(), False
        ql = q.get("text", "").lower()
        for t in terms:
            tb = _bigrams(t["term"]) | _bigrams(t["root"])
            latin_hit = any(w in ql for w in tb if re.match(r"[a-z]{4,}", w))
            if latin_hit or len(qb & tb) >= 2:
                hits.append(t["term"])
                roots.add(t["root"])
                has_new = has_new or t.get("new", False)
        if hits:
            demand[q["id"]] = {"terms": hits[:5], "n": len(hits),
                               "roots": sorted(roots)[:4], "new": has_new}
    return demand


# ---------------------------------------------------------------- LLM 转写

CONVERT_PROMPT = """下面每行是一个真实的搜索下拉词。把每行改写成一个真实用户会向 AI 助手提出的自然问句。

硬性要求：
- 中文词出中文问句，英文词出英文问句（英文要原生问法，不是翻译腔）
- 保留原词的核心意图与实体，不新增原词没有的信息
- 一行进一行出，行数一致，只输出 JSON：{"questions": ["...", "..."]}

搜索词：
"""


def _convert_llm(terms: list[dict]) -> bool:
    """有 Key 就用 LLM 把搜索词转成问句；没有或失败返回 False，走模板。

    分批各 40 行：批量太大时行数极易对不上，小批失败只影响该批（保留模板问句）。"""
    import sample as S
    plat = S.pick_llm()
    if not plat or not terms:
        return False
    ok_any = False
    for i in range(0, len(terms), 40):
        chunk = terms[i:i + 40]
        res = S.ask(plat, CONVERT_PROMPT + "\n".join(t["term"] for t in chunk), timeout=180)
        if not res.get("ok"):
            continue
        m = re.search(r"\{.*\}", res["answer"], re.S)
        if not m:
            continue
        try:
            qs = json.loads(m.group(0)).get("questions") or []
        except Exception:  # noqa: BLE001
            continue
        if len(qs) != len(chunk):
            continue
        for t, q in zip(chunk, qs):
            if isinstance(q, str) and q.strip():
                t["question"] = q.strip()
        ok_any = True
    return ok_any


# ---------------------------------------------------------------- 主流程

def run(slug: str, use_llm: bool = True) -> dict:
    cfg = G.load_config(slug)
    path = G.project_dir(slug) / "expand.json"
    prev = G.read_json(path, {}) or {}
    first_seen = {t["term"]: t.get("first_seen") or prev.get("generated_at", "")
                  for t in prev.get("terms", [])}

    roots = _roots(cfg)
    today = G.today()
    proj_market = cfg.get("market", "cn")
    seen, terms = set(), []
    root_n: dict[str, int] = {r["root"]: 0 for r in roots}
    n_calls = 0

    for r in roots:
        mkts = ["cn", "global"] if (r["market"] or proj_market) == "both" else [r["market"] or proj_market]
        for mk in mkts:
            for mod in MODS[mk][r["kind"]]:
                q = r["root"] + mod
                sugs = None
                for _ in range(2):          # 公网端点偶发抖动，重试一次
                    try:
                        sugs = suggest_baidu(q) if mk == "cn" else suggest_google(q)
                        break
                    except Exception as e:  # noqa: BLE001
                        err = type(e).__name__
                        time.sleep(0.5)
                if sugs is None:
                    G.info(f"  拓词请求失败（{q}）：{err}")
                    continue
                n_calls += 1
                time.sleep(0.15)          # 对公开端点保持克制
                for s in sugs[:10]:
                    key = s.strip().lower()
                    if not key or key == r["root"].lower() or key in seen:
                        continue
                    if not _relevant(s, r["root"]):
                        continue            # 前缀漂移到无关实体的词，直接丢
                    if root_n[r["root"]] >= 25 or len(terms) >= 200:
                        continue
                    root_n[r["root"]] += 1
                    seen.add(key)
                    grp = _classify(s, r["kind"])
                    st = s.strip()
                    if re.search(r"[？?]$", st):
                        qtext = st
                    elif re.search(r"是什么|怎么|如何|哪个|哪些|多少钱|吗$|^how |^what |^which |^is |^can ", st, re.I):
                        qtext = st + ("？" if mk == "cn" else "?")
                    else:
                        qtext = TEMPLATES[mk][grp].format(t=st)
                    terms.append({"term": st, "root": r["root"], "kind": r["kind"],
                                  "market": mk, "group": grp,
                                  "question": qtext,
                                  "first_seen": first_seen.get(s.strip(), today),
                                  "new": s.strip() not in first_seen})

    llm_used = use_llm and _convert_llm(terms)
    existing = {q.get("text", "").strip().lower() for q in cfg.get("questions") or []}
    for t in terms:
        t["in_bank"] = t["question"].strip().lower() in existing

    out = {"generated_at": today, "calls": n_calls, "llm": llm_used,
           "roots": roots, "terms": terms,
           "q_demand": _match_questions(cfg, terms)}
    G.write_json(path, out)
    G.info(f"拓词完成：{len(roots)} 个词根 → {len(terms)} 条候选"
           f"（新词 {sum(1 for t in terms if t['new'])}，问句转写：{'LLM' if llm_used else '模板'}）")
    return out
