---
name: geo
description: >-
  完整的 GEO（生成式引擎优化）服务流水线：给一个产品官网 URL 和介绍材料，
  做站点诊断与 AI 答案采样、生成带验收标准的执行工单、产出可直接部署的资产
  （llms.txt / JSON-LD / 定义块 / FAQ / 内容大纲与初稿）、自动验收工单是否闭环、
  并打包成可直接发给客户的交付物。可按周期复跑，做长期 GEO 运营与月报。
  国内和海外双市场并行：国内覆盖 智谱GLM/豆包/DeepSeek/Kimi/MiniMax/纳米AI/百度AI，
  海外覆盖 Gemini/ChatGPT/Claude/Grok/Perplexity，问题库与指标按市场分开算。
  当用户说「做 GEO」「生成式引擎优化」「让 AI 推荐我的产品」「AI 搜索里搜不到我们」
  「GEO 方案/诊断/监测/月报/交付」「给客户做 GEO 服务」，或给一个产品网址要做
  AI 可见性优化时使用。GEO 指生成式引擎优化，不是地理信息；
  不用于传统 SEO 关键词排名、竞价投放或建站。
---

# GEO 全流程服务

从**诊断**到**交付**的完整链路，不只是给建议：

```
抓取 → 体检 → AI答案采样 → 生成工单 → 产出资产 → 报告 → 自动验收 → 客户交付包
```

核心判断只有一句：**GEO 的终点不是排名，是 AI 答案里那句话是不是按你的口径说的。**
所以最小单位不是页面，是**可被抽取的事实块**。

项目目录：`/Users/brucejan/geo`，每个客户/产品一个 `work/<slug>/`。

---

## 最快的用法：给一个网址

```bash
python3 scripts/geo.py new --url https://example.com --market both
```

九步全自动：建项目 → 抓官网 → 体检 → **自动推导品牌事实/竞品/问题库** →
重跑体检 → AI 答案采样 → 工单与建设蓝图 → 资产与报告 → 三份交付物。

产出 `work/<slug>/deliverables/`：

| 文件 | 回答什么 |
|---|---|
| `1-GEO诊断报告.html` | 现在什么样 |
| `2-GEO优化方案.html` | 应该改成什么样、为什么 |
| `3-GEO执行方案.html` | 谁在什么时候做什么、做到什么算完成 |

**自动推导出来的品牌事实必须人工复核**——`bootstrap` 只从官网正文抽取，
抽不到的一律标「待确认」，绝不用常识填充。标了「待确认」的字段
（成立时间、工商主体、可具名客户等）需要你补齐或明确不对外说。

## 两种用法

### 界面（推荐）

```bash
python3 scripts/geo.py ui        # 默认 http://127.0.0.1:8765
```

**全流程都在界面上**，不用记命令：新建项目、编辑配置与问题库、写事实卡、
一键跑任意步骤或整个周期（带实时日志）、改工单状态、看资产、导入人工采样表、打开交付包。

界面为暗色四段主线（AtlasGEO）：**现状**（总览 / 引擎表现 / 竞品对比 / 问题库）→ **诊断**（差距诊断 / 阵地地图 / 品牌事实库）→ **提升**（行动计划 / 内容工作台）→ **成效**（效果验收 / 报告与交付），外加设置与三步接入引导。统一口径：GEO 健康分（五项加权，未测项权重归一）、提及率、引用份额、阵地、任务、内容。总览标题是由数据自动生成的一句结论；所有数字来自同一份采样，算不出的显示「未测」，不编数。
任务在后台子进程跑，关掉页面也会继续；同一项目同时只允许一个任务，避免抢同一份 audit.json。

只用标准库起服务，前端零外部依赖，断网可用。

### 命令行

```bash
python3 scripts/geo.py serve --slug <项目>
```

抓取 → 体检 → 采样 → 工单 → 资产 → 报告 → 验收上期 → 打包交付，全做完。
产出在 `work/<slug>/delivery/<日期>/`，可直接发客户。

首次接一个新客户走下面的步骤 0–2 做好底座，之后每期只跑这一条。

---

## 先读什么

- **每次必读**：`references/method.md`（评分口径和所有判据的出处，脚本就是它的代码实现）
- **排外部信源优先级时必读**：`references/cn-source-ranking.md`
  （CN-GEO 187,818 条引用实算榜。**官网只占 1.37%**，这个数字会改变资源分配）
- 打国内平台：`references/cn-platforms.md` ｜ 打海外：`references/global-platforms.md`
- 写内容/改页面：`references/content-patterns.md`
- 更深方法或原始数据：`references/sources.md`（含 GEORank / GEOFlow 选型说明）

不要凭经验给 GEO 建议。**每条建议都要能追到 `method.md` 里的某条实测数字**，
说不出依据的别写进方案。

---

## 步骤 0 · 建项目

```bash
python3 scripts/geo.py init --url <产品官网> --name <品牌名> --market both
```

`--market` 取 `cn` / `global` / `both`。

**双市场不是"顺带也做海外"**，是两套并行的战场——问题库、内容、竞品清单、指标全部分开。
纪律见 `global-platforms.md` 第 5 节。

## 步骤 1 · 吃透产品，建事实底座

读官网 + 用户给的材料（PDF/PPT/文档/公众号文章都行），补全 `geo.json`：

- `brand`：规范名、**别名和常见错写**（品牌消歧的地基）、产品线、行业、目标用户、业务目标
- `competitors`：3–6 个真实竞品，带别名。**首期可以留空**——先跑一轮"推荐类"问题的采样，
  从 AI 答案里反推真实竞争集，比主观拍脑袋准得多。双市场时国内外竞品通常不是同一批，都要列全
  （排名指标是相对这个清单算的，漏掉真实对手会**高估**名次）

同时写 `work/<slug>/content/facts.md` 品牌事实卡，模板见 `content-patterns.md` 第 1 节。
**每条事实标证据等级 A–E，没来源的标"待确认"，不许编。**
这份文件是后面所有资产生成的输入——`llms.txt`、JSON-LD、定义块都从它来。

材料不够就直接问用户要，别猜产品能力和价格。

## 步骤 2 · 建问题库

问题库决定采样什么、写什么内容、怎么算指标。按七组各出 3–6 题：
推荐 / 比较 / 替代 / 价格 / 风险 / 品牌验证 / 场景。

**每题必须标 `market`**，脚本据此路由——中文题不会打到 Perplexity，英文题不会打到豆包：

```json
{"id": "q001", "group": "推荐", "market": "cn",     "text": "国内做私域运营的 SaaS 有哪些好用的？"}
{"id": "q101", "group": "推荐", "market": "global", "text": "What's the best CRM for small B2B teams in 2026?"}
{"id": "q900", "group": "品牌验证", "market": "both", "text": "<品牌> 是家什么公司？"}
```

- `cn`：中文口语问法，不要翻译腔 ｜ `global`：**英文原生问法**，不是机翻
- `both` 只留给品牌验证类。注意这类问题**点名了品牌**，答案必然复述品牌名，
  脚本会把它们单独归入「品牌认知」，不混进可见性指标

---

## 每期循环（`serve` 自动做完，这里说明每步在干什么）

### 抓取 + 体检

按六维打分：可抓取性 / 长度 / 结构 / **可抽取块** / 权威信号 / 对题性。
读结果时先看四件事：

1. **SPA 空壳页**（`word_count` 接近 0）——国内官网最常见致命伤，AI 抓取器看到的是空白
2. **robots 有没有封 AI 抓取器**——封了就什么都别谈
3. **`language_coverage` 中英是否对等**——做海外却没英文原生页直接 P0
4. **`block_gap` 缺得最多的块**——内容工程第一优先级

### AI 答案采样

| 市场 | 平台 | 变量 | 说明 |
|---|---|---|---|
| 国内 | 智谱GLM | `ZHIPUAI_API_KEY` | OpenAI 兼容端点，不联网 |
| 国内 | 豆包 | `ARK_API_KEY` | 火山方舟；**联网要在控制台单独开通内容插件**，没开通自动降级 |
| 国内 | DeepSeek | `DEEPSEEK_API_KEY` | 不联网，测模型参数化知识里的品牌认知 |
| 国内 | Kimi | `MOONSHOT_API_KEY` | 默认不联网 |
| 国内 | MiniMax | `MINIMAX_API_KEY` | OpenAI 兼容端点，不联网 |
| 海外 | Gemini | `GEMINI_API_KEY` | OpenAI 兼容端点，不带 grounding |
| 海外 | OpenAI(ChatGPT) | `OPENAI_API_KEY` | Chat Completions 默认不联网 |
| 海外 | Claude | `ANTHROPIC_API_KEY` | Anthropic 原生协议，不联网 |
| 海外 | Grok | `XAI_API_KEY` | xAI API，不联网 |
| 海外 | Perplexity | `PERPLEXITY_API_KEY` | 原生联网并返回 citations，海外证据质量最好 |

Key 放项目根目录 `.env`（已 gitignore，权限 600），脚本自动加载。

没有公开联网 API 的——国内纳米AI搜索/百度AI/豆包 App，海外 ChatGPT 网页版/
Claude 网页版——走人工或浏览器采样：

```bash
python3 scripts/geo.py sample-sheet --slug <项目>
python3 scripts/geo.py sample-import --slug <项目> --file <采样表>
```

**口径纪律**（详见 `method.md` 第 4 节）：

- **国内 ≠ 海外**，跨市场平均提及率没有解释力，报告里各占一张表
- API ≠ 网页端，Web ≠ App（**千问 web 与 App 信源只有 24.5% 重合**），单独记单独算
- 没有答案原文/截图/采样环境记录的，**不许标成"真实采样"**
- 归因默认写"观察相关"，除非有基线窗口 + 对照 Prompt + 竞品对照
- 采样频率克制，遵守平台服务条款，不批量滥采、不模拟登录

### 生成工单 `plan`

诊断结果 → `tasks.json`，这是执行状态的**单一真相源**。每条工单必须有：
依据（追到 `method.md` 哪一条）、负责角色、工作量、时间窗口、**验收标准**、市场。

七个工作包：实体消歧 / 页面技术 / 内容矩阵 / 标题体系 / 知识库 / 外部证据 / 监测闭环。

优先级顺序（`method.md` 第 6 节）：
门票问题 → 事实错误 → 抽取块缺口 → 高价值问题无承接 → **外部信源（P1，不是 P2）** → 长尾扩量。

> 外部信源是 P1 不是 P2，因为**官网只占全库引用 1.37%**。
> 官网是事实源不是引用源，把它从 60 分做到 90 分的边际收益，远低于拿下一个榜单站词条。

### 产出资产 `generate`

到 `work/<slug>/assets/`，中英分开：

| 产物 | 说明 |
|---|---|
| `llms.txt` / `llms.en.txt` | 官方事实索引，直接传网站根目录 |
| `jsonld/*.json` | Organization / SoftwareApplication / FAQPage / Article / BreadcrumbList，贴进 `<head>` |
| `snippets/definition.*.html` | 定义块，放首屏口号下方（口号保留，不影响转化） |
| `snippets/faq.*.html` | FAQ 块，**答案必须在静态 HTML 里可见**，不要纯 JS 折叠 |
| `outlines/*.md` | 每个目标问题一份内容大纲（含标题候选、章节骨架、字数与抽取块要求） |
| `drafts/*.md` | 加 `--draft` 时调用已配 LLM 出全文初稿 |

**分工**：结构性资产由代码确定性生成（不会漏 schema 字段）；**文章正文由你按 outline 写**——
代码写不出好文案。`--draft` 的初稿**必须人工核实事实后才能发布**。

### 自动验收 `verify`

重抓站点 → 跑 checker → 回写工单状态。**这是"服务"和"建议"的分界线**：
能自动验收的，就不靠人口头说做完了。做完会翻成 `done`，回归了会翻回 `todo`。

无法程序判定的（如百科词条是否过审）标「待人工」，确认后手动标记：

```bash
python3 scripts/geo.py task --slug <项目> --id T-003 --status done --note "词条已上线"
python3 scripts/geo.py status --slug <项目>     # 进度看板
```

### 客户交付 `deliver`

打包到 `work/<slug>/delivery/<日期>/`：总览 index、诊断报告、执行方案、
工单表（HTML + CSV 可导进项目管理工具）、验收表、assets 目录、交付说明。

跑完之后你要做的事（脚本做不了的部分）：

1. 读 `reports/latest.md` 看 delta：均分涨跌、提及率变化、新出现的 P0
2. **看「AI 实际引用的信源域名 Top」和「与全国大盘对照」**——这是当期真实的分发地图，
   用它修正外部信源计划
3. 检查采样答案里有没有**事实错误**（品牌说错、张冠李戴、价格错、**归错行业**）→ 立刻 P0
4. 按 `outlines/` 写内容，按 `plan.md` 更新进度

建议节奏：**页面体检每周，答案采样每两周或每月**（采样有成本，指标本身有噪声，跑太密看不出信号）。

---

## 全部命令

| 命令 | 作用 |
|---|---|
| `new` | **★ 只给一个网址，全自动出三份交付物** |
| `autopilot` | 对已建好的项目跑完整引导流程 |
| `bootstrap` | 从官网正文推导品牌事实、竞品、问题库 |
| `deliverables` | 出三份正式交付物（诊断/优化/执行） |
| `init` | 只建项目骨架，不跑流程 |
| `crawl` / `audit` | 抓站 / 六维体检 |
| `sample` / `sample-sheet` / `sample-import` | API 采样 / 导出人工采样表 / 回灌 |
| `plan` | 诊断结果 → 带验收标准的工单 |
| `generate` | 产出可部署资产（`--draft` 加 LLM 初稿） |
| `report` | Markdown + 自包含 HTML 报告，含 delta 与大盘对照 |
| `verify` | 重抓并自动验收工单（`--no-recrawl` 用现有结果） |
| `task` / `status` | 单条工单状态 / 项目看板 |
| `deliver` | 打包客户交付物 |
| `ui` | **全流程界面**：新建项目、配置、问题库、事实卡、一键运行、工单、资产、交付 |
| `serve` | **全流程一条命令** |
| `cycle` | 轻量循环（抓取→体检→采样→报告，不含工单与交付） |
| `list` | 所有项目 |

## 排期自动执行

用 `schedule` skill 建定时任务：

> 每周一早上跑 `python3 /Users/brucejan/geo/scripts/geo.py serve --slug <项目>`，
> 然后读 `work/<项目>/reports/latest.md`，如果出现新的 P0、提及率下降超过 10 个百分点，
> 或有工单从 done 回归成 todo，就告诉我。

---

## 边界

**做**：GEO 诊断、方案、工单、内容工程、资产生成、AI 答案监测、验收闭环、客户交付包。

**不做**：
- 传统 SEO 关键词排名、外链买卖、竞价投放
- 建站/改站的实际代码实施（给方案、给可直接用的片段，落地由客户开发做）
- 绕过平台限制的批量采集、模拟登录、刷量
- 编造品牌事实、客户案例、价格或资质——**查不到就标"待确认"，问用户**

**不承诺**任何平台一定会引用某个页面。GEO 提高的是概率，不是保证。
给客户写方案时这句话必须原样写进去。

---

## 目录

```text
/Users/brucejan/geo/
├── SKILL.md
├── references/
│   ├── method.md              评分口径与全部判据出处
│   ├── cn-source-ranking.md   国内信源实测榜（CN-GEO 实算，含复算脚本）
│   ├── cn-platforms.md        国内平台适配
│   ├── global-platforms.md    海外平台适配
│   ├── content-patterns.md    可抽取内容模板
│   └── sources.md             资料索引（含 GEORank / GEOFlow 选型）
├── scripts/
│   ├── geo.py       CLI 总入口
│   ├── crawl.py     抓站      audit.py     六维体检
│   ├── sample.py    多平台采样  benchmark.py 与全国大盘对照
│   ├── tasks.py     工单系统    generate.py  资产生成
│   ├── verify.py    自动验收    deliver.py   客户交付包
│   ├── bootstrap.py 自动推导底座  deliverables.py 三份交付物
│   ├── blueprint.py 建设地图
│   ├── dashboard.py 界面后端    ui.html      前端工作台
│   ├── jobs.py      后台任务（子进程 + 实时日志）
│   └── report.py    报告渲染    geolib.py    共用工具
└── work/<slug>/
    ├── geo.json        品牌、竞品、问题库、平台、目标
    ├── content/facts.md 品牌事实卡（所有资产的输入）
    ├── evidence/       抓取快照      audit.json  体检结果
    ├── samples/        采样原始答案   metrics/    每期指标
    ├── tasks.json      工单（执行状态单一真相源）
    ├── assets/         可部署资产
    ├── reports/        每期报告 + latest.md
    ├── verify/         每期验收结果
    ├── delivery/<日期>/ 客户交付包
    ├── history/        历史基线（算 delta）
    └── plan.md         30/60/90 方案
```
