"""自动引导：只给一个网址，把项目底座建起来。

原本 init 之后必须人工填的三样东西——品牌事实卡、竞品清单、问题库——
这里用「抓取的官网正文 + LLM 抽取」自动生成初稿。

**编造防线**（这是本模块最重要的部分）：
  1. 只从抓到的官网正文里抽事实，不许 LLM 补充站外知识
  2. 抽出来的每条事实标证据等级，抽不到的一律写「待确认」，不允许留空猜
  3. 竞品分两步：LLM 先提候选，再由真实采样确认——没被 AI 答案提到的不算竞品
  4. 生成完自动跑一遍事实核对，把正文里查无实据的数字标出来

产出：geo.json（brand/competitors/questions）+ content/facts.md
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import geolib as G

GROUPS = ["推荐", "比较", "替代", "价格", "风险", "品牌验证", "场景"]


def _site_digest(slug: str, limit: int = 14000) -> str:
    """把抓到的页面正文压成一份摘要喂给 LLM。首页和高分页优先。"""
    pages = G.read_jsonl(G.project_dir(slug) / "evidence" / "pages.jsonl")
    if not pages:
        return ""
    audit = G.read_json(G.project_dir(slug) / "audit.json", {})
    score = {p["url"]: p["score"] for p in audit.get("pages", [])}
    root = pages[0]["url"]  # pages.jsonl 第一条即首页，摘要首块必须是它
    ordered = sorted(pages, key=lambda p: (p["url"] != root, -score.get(p["url"], 0)))

    parts, used = [], 0
    for p in ordered:
        if not p.get("text"):
            continue
        block = (f"\n## 页面：{p.get('title') or p['url']}\nURL: {p['url']}\n"
                 f"{p['text'][:2600]}\n")
        if used + len(block) > limit:
            break
        parts.append(block)
        used += len(block)
    return "".join(parts)


def _ask_json(prompt: str, provider: str | None = None, timeout: int = 300) -> dict | None:
    """调 LLM 并解析出 JSON。抽不出就返回 None，由调用方降级处理。"""
    import sample as S

    cands = [provider] if provider else ["deepseek", "glm", "doubao", "openai", "gemini"]
    plat = next((p for p in cands if p and S.available(p)), None)
    if not plat:
        return None
    res = S.ask(plat, prompt, timeout=timeout)
    if not res.get("ok"):
        G.info(f"  LLM 调用失败：{str(res.get('error'))[:120]}")
        return None
    txt = res["answer"]
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", txt, re.S) or re.search(r"(\{.*\})", txt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:  # noqa: BLE001
        # 常见毛病：尾逗号、中文引号
        s = m.group(1).replace("，", ",").replace("：", ":")
        s = re.sub(r",\s*([}\]])", r"\1", s)
        try:
            return json.loads(s)
        except Exception:  # noqa: BLE001
            return None


# ---------------------------------------------------------------- 品牌事实

BRAND_PROMPT = """你是 GEO（生成式引擎优化）分析师。下面是从一个产品官网抓取的正文内容。

请**只根据这些正文**抽取品牌事实，输出 JSON。这是硬性纪律：

- **绝对不要补充正文里没有的信息**。你可能"知道"这个品牌的其他情况，但那不算数
- 正文里找不到的字段，值写 "待确认"，不要猜、不要留空、不要用常识填充
- 数字必须原样引用正文，不要换算、不要取整、不要估计
- 如果品牌名可能被误解成其他行业（例如名字里有歧义词），在 disambiguation 里写明

输出 JSON，字段如下（不要输出任何解释文字）：

{
  "name": "品牌规范名",
  "aliases": ["别名或常见简写，从正文里出现过的写法中取"],
  "products": ["产品线或核心能力名称"],
  "industry": "所属行业/品类，用一个短语",
  "target_users": "目标用户，越具体越好",
  "business_goal": "推测的商业目标（注册转化/付费订阅/线索获取等）",
  "definition": "一句话定义。必须以品牌名开头，先说清目标客群和品类词，再说做什么。60-120字",
  "key_numbers": [{"fact":"这个数字说明什么","value":"数值原文","source":"来自哪个页面"}],
  "suitable": ["适合谁，2-4条"],
  "unsuitable": ["不适合谁，1-3条。正文没写就根据产品定位合理推断，并在末尾标(推断)"],
  "disambiguation": ["需要澄清的口径，1-3条。没有就给空数组"],
  "pricing": [{"name":"套餐名","price":"价格原文","currency":"币种","desc":"含什么"}],
  "uncertain": ["你没能从正文确认、但对 GEO 很重要的信息，例如成立时间、工商主体、可具名客户"]
}

官网正文：
"""


def brand_facts(slug: str, digest: str) -> dict | None:
    G.info("  推导品牌事实…")
    return _ask_json(BRAND_PROMPT + digest)


# ---------------------------------------------------------------- 问题库

QUESTION_PROMPT = """你是 GEO 分析师。根据下面的品牌信息，设计一套「用户会拿去问 AI 的问题库」。

品牌：{name}
品类：{industry}
目标用户：{target_users}
一句话定义：{definition}

要求：

1. 分七组：推荐、比较、替代、价格、风险、品牌验证、场景。每组 2-4 题
2. **用目标市场用户的真实口语说法**，完整问句，不是关键词堆砌
3. 市场标记规则：
   - "cn"：中文问法。不要翻译腔，要像真人在国内 AI 里会打的字
   - "global"：**英文原生问法**，不是把中文题翻译过去。海外用户不会问"哪个更香"
   - "both"：只给品牌验证类（这类点名了品牌）
4. 绝大多数问题**不要出现品牌名**——考的是 AI 会不会主动想到你。只有品牌验证组可以点名
5. 市场范围：{market_hint}

输出 JSON（不要任何解释）：

{{"questions":[{{"id":"q001","group":"推荐","market":"cn","text":"问题原文"}}]}}

编号规则：国内题 q001 起，海外题 q101 起，通用题 q901 起。
"""


def question_bank(brand: dict, market: str) -> list[dict]:
    hint = {"cn": "只出国内（cn）问题，18-24 题",
            "global": "只出海外（global）问题，14-20 题",
            "both": "国内 16-20 题 + 海外 12-16 题 + 通用 2 题"}[market]
    G.info("  设计问题库…")
    data = _ask_json(QUESTION_PROMPT.format(
        name=brand.get("name", ""), industry=brand.get("industry", ""),
        target_users=brand.get("target_users", ""), definition=brand.get("definition", ""),
        market_hint=hint))
    qs = (data or {}).get("questions") or []
    out, seen = [], set()
    for q in qs:
        t = (q.get("text") or "").strip()
        mk = q.get("market") if q.get("market") in ("cn", "global", "both") else market
        if not t or t in seen or (market != "both" and mk not in (market, "both")):
            continue
        seen.add(t)
        out.append({"id": q.get("id") or f"q{len(out)+1:03d}",
                    "group": q.get("group") if q.get("group") in GROUPS else "推荐",
                    "market": mk, "text": t})
    return out


# ---------------------------------------------------------------- 竞品

COMPETITOR_PROMPT = """列出下面这个产品在市场上的**真实竞品**。

产品：{name}
品类：{industry}
定位：{definition}

纪律：

- 只列**真实存在、可以搜到官网**的产品或公司名，**严禁发明名字**
- 严禁使用"工具A""某某Pro""XX方案"这类占位名
- 想不出足够多就少列几个，宁缺毋滥
- 国内竞品和海外竞品通常不是同一批，分开标
- 如果这个品类里用户其实是拿通用工具替代的（例如直接用 ChatGPT），把"通用大模型"也列进去

输出 JSON（不要解释）：

{{"competitors":[{{"name":"真实产品名","aliases":["别名"],"market":"cn"}}]}}
"""


def competitors(brand: dict, market: str) -> list[dict]:
    G.info("  推导竞品候选…")
    data = _ask_json(COMPETITOR_PROMPT.format(
        name=brand.get("name", ""), industry=brand.get("industry", ""),
        definition=brand.get("definition", "")))
    rows = (data or {}).get("competitors") or []
    fake = re.compile(r"(工具\s*[A-Z一二三四五六七八九十]|某某|XX|示例|competitor\s*[a-z]|foobar|acme)", re.I)
    out = []
    for c in rows:
        n = (c.get("name") or "").strip()
        if not n or fake.search(n) or n == brand.get("name"):
            continue
        mk = c.get("market") if c.get("market") in ("cn", "global", "both") else market
        if market != "both" and mk not in (market, "both"):
            continue
        out.append({"name": n, "aliases": [a for a in (c.get("aliases") or []) if a],
                    "market": mk, "confirmed": False})
    return out[:14]


# ---------------------------------------------------------------- 事实卡

def render_facts(slug: str, brand: dict) -> str:
    cfg = G.load_config(slug)
    site = cfg["brand"]["site"]
    L = [f"# {brand.get('name','')} · 品牌事实卡", "",
         f"> 由 `bootstrap` 从官网正文自动抽取（{G.today()}），**每条都需人工复核**。",
         "> 证据等级：`A 官方已证实` / `B 第三方可佐证` / `C 内部待授权` / `D 需补证` / `E 禁止使用`。",
         "> 标「待确认」的字段官网上找不到，**必须人工补齐或明确不对外说**。", "",
         "## 实体", "", "| 项 | 值 | 证据 |", "|---|---|---|",
         f"| 规范名 | {brand.get('name','待确认')} | A 官网 |",
         f"| 别名 | {'、'.join(brand.get('aliases') or []) or '待确认'} | A 官网 |",
         f"| 官网 | {site} | A |",
         f"| 行业 | {brand.get('industry','待确认')} | A 官网 |"]

    # 待确认项要接在同一张表里，另起一段会被渲染成两张表
    for u in (brand.get("uncertain") or []):
        L.append(f"| {u} | **待确认** | D 需补证 |")
    L += ["", "## 一句话定义", "",
          f"> {brand.get('definition','（待补：以品牌名开头，先说目标客群和品类词）')}", "",
          "**这句话必须在四处逐字一致**：官网首屏、关于页、JSON-LD `description`、`llms.txt`。",
          "口径不一致是 AI 描述品牌漂移的头号原因。", ""]

    dis = brand.get("disambiguation") or []
    if dis:
        L += ["## 实体消歧", "",
              "以下口径需要在官网、百科和对外材料中保持一致：", ""]
        L += [f"{i+1}. {d}" for i, d in enumerate(dis)]
        L.append("")

    nums = brand.get("key_numbers") or []
    L += ["## 关键数字", "", "| 事实 | 数值 | 来源 | 证据 |", "|---|---|---|---|"]
    for n in nums:
        L.append(f"| {n.get('fact','')} | {n.get('value','')} | {n.get('source','官网')} | A |")
    if not nums:
        L.append("| （官网未提取到可用数字，需人工补充） | 待确认 | — | D |")
    L.append("")

    pr = brand.get("pricing") or []
    if pr:
        L += ["## 定价", "", "| 版本 | 价格 | 含什么 |", "|---|---|---|"]
        for p in pr:
            L.append(f"| {p.get('name','')} | {p.get('price','')} {p.get('currency','')} | {p.get('desc','')} |")
        L.append("")

    L += ["## 适用与不适用", ""]
    L += ["**适合**：", ""] + [f"- {x}" for x in (brand.get("suitable") or ["待确认"])] + [""]
    L += ["**不适合**：", ""] + [f"- {x}" for x in (brand.get("unsuitable") or ["待确认"])] + [""]
    L += ["> 写清楚「不适合谁」反而提高可信度和被引用率——只说好话的内容 AI 会当成营销文案。", ""]

    comps = cfg.get("competitors", [])
    if comps:
        L += ["## 竞品", "", "| 竞品 | 市场 | 状态 |", "|---|---|---|"]
        for c in comps:
            status = "已采样确认" if c.get("confirmed") is not False else "**未经采样确认**"
            L.append(f"| {c.get('name','')} | {c.get('market','')} | {status} |")
        L += ["> 「未经采样确认」的竞品是 LLM 候选，尚未在真实 AI 答案里出现过，对外内容不要点名。", ""]

    L += ["## 禁用表达", "",
          "- 不要说：任何官网上没有、也无法核实的客户名、数据、资质",
          "- 不要说：绝对化表述（国内第一、行业领先）",
          "- 不要说：把 AI 生成的结果描述成无需人工审核即可使用", "",
          "## 待人工处理", "",
          "1. 逐条核对上表，把「待确认」补齐或确认不对外说",
          "2. 补充工商主体、成立时间等实体信息（AI 回答「是家什么公司」时会用到）",
          "3. 争取至少 1 个可具名的客户案例——匿名案例在 GEO 里可引用性很低", ""]
    return "\n".join(L)


# ---------------------------------------------------------------- 主流程

def run(slug: str, skip_llm: bool = False) -> dict:
    cfg = G.load_config(slug)
    market = cfg.get("market", "cn")
    digest = _site_digest(slug)
    if not digest:
        G.die("没有抓取结果，先运行 crawl")

    G.info(f"自动引导：从 {len(digest)} 字官网正文推导项目底座")
    if skip_llm:
        G.info("  --skip-llm：跳过 LLM 推导，只建空底座")
        return cfg

    brand = brand_facts(slug, digest)
    if not brand:
        G.info("  LLM 不可用或返回无法解析，底座留空，需人工填写")
        return cfg

    b = cfg["brand"]
    b["name"] = brand.get("name") or b["name"]
    for k_cfg, k_llm in (("aliases", "aliases"), ("products", "products")):
        v = brand.get(k_llm)
        if isinstance(v, list) and v:
            b[k_cfg] = [x for x in v if x and x != "待确认"]
    for k in ("industry", "target_users", "business_goal"):
        v = brand.get(k)
        if v and v != "待确认":
            b[k] = v
    if brand.get("disambiguation"):
        b["disambiguation"] = brand["disambiguation"]
    if brand.get("pricing"):
        b["offers"] = [{"name": p.get("name", ""), "price": str(p.get("price", "")),
                        "currency": p.get("currency", "CNY"), "desc": p.get("desc", "")}
                       for p in brand["pricing"]]

    cfg["competitors"] = competitors(brand, market) or cfg.get("competitors", [])
    cfg["questions"] = question_bank(brand, market) or cfg.get("questions", [])
    cfg["bootstrap"] = {"at": G.now_iso(), "source": "官网正文 + LLM 抽取",
                        "uncertain": brand.get("uncertain") or [],
                        "needs_review": True}
    G.save_config(slug, cfg)

    fp = G.project_dir(slug) / "content" / "facts.md"
    fp.parent.mkdir(parents=True, exist_ok=True)
    if fp.exists():
        (fp.parent / f"facts.bootstrap-{G.today()}.md").write_text(render_facts(slug, brand), "utf-8")
        G.info("  已有 facts.md，自动版另存为 facts.bootstrap-<日期>.md，请人工合并")
    else:
        fp.write_text(render_facts(slug, brand), "utf-8")

    qs = cfg["questions"]
    G.info(f"完成：竞品 {len(cfg['competitors'])} 个、问题 {len(qs)} 题"
           f"（国内 {sum(1 for q in qs if q['market']=='cn')}"
           f" / 海外 {sum(1 for q in qs if q['market']=='global')}"
           f" / 通用 {sum(1 for q in qs if q['market']=='both')}）")
    if brand.get("uncertain"):
        G.info("  官网未提供、需人工补齐：" + "、".join(brand["uncertain"][:5]))
    return cfg
