<div align="center">

# Geo**Look**

**开源的全流程 GEO 实施平台 · 自托管**

面向具体项目：现状分析 → 诊断 → 方案 → 实施计划工单 → 执行落地 → 效果验收

简体中文 · [English](README.en.md)

![License](https://img.shields.io/badge/license-MIT-9184d9) ![Python](https://img.shields.io/badge/python-3.9%2B-9184d9) ![Deps](https://img.shields.io/badge/deps-requests%20·%20bs4%20·%20lxml-9184d9)

</div>

> GEO 指生成式引擎优化（Generative Engine Optimization）——让 DeepSeek、豆包、ChatGPT、Perplexity 这些 AI 引擎在回答用户问题时**主动提到并引用你的品牌**。不是地理信息，也不是传统 SEO。

![总览](docs/screenshots/overview.png)

## 它做什么

GeoLook 不是又一个「GEO 监测仪表盘」——它交付的是**特定项目的全流程 GEO 实施**：从现状分析、诊断出发，产出可执行的方案与实施计划工单，跟到执行落地并自动验收，最后打包成可交付的成果。给一个产品官网，它回答四个问题：

| 阶段 | 回答 | 页面 |
|---|---|---|
| **现状** | AI 里你是什么样 | 总览 / 引擎表现 / 竞品对比 / 问题库 |
| **诊断** | 为什么是这样 | 站点体检 / 差距诊断 / 阵地地图 / 品牌事实库 |
| **提升** | 该做什么 | 行动计划 / 内容工作台 / 部署资产 |
| **成效** | 做了有没有用 | 效果验收 / 报告与交付 |

一条命令跑通全流程：

```bash
python3 scripts/geo.py new --url https://example.com --market both
```

九步全自动：抓取官网 → 六维体检 → 从正文推导品牌事实/竞品/问题库 → 逐引擎采样 AI 答案 → 生成带验收标准的工单 → 产出可部署资产（llms.txt / JSON-LD / 定义块 / FAQ / 内容初稿）→ 报告 → 自动验收 → 客户交付包。

## 核心特性

### 双市场引擎观测

国内海外分开出题、分开采样、分开算指标——中文题不会打到 Perplexity，英文题不会打到豆包。

| 市场 | API 自动采样 | 人工采样表 |
|---|---|---|
| 国内 | 智谱GLM · 豆包(方舟) · DeepSeek · Kimi · MiniMax | 纳米AI搜索 · 百度AI · 豆包App |
| 海外 | Gemini · OpenAI(ChatGPT) · Claude · Grok · Perplexity | ChatGPT网页版 · Claude网页版 |

![引擎表现](docs/screenshots/engines.png)

### 可复现的指标口径

- **提及率**：无提示样本中 AI 主动提到品牌的比例（点名了品牌的问题剔除，防 100% 假阳性）
- **引用份额**：AI 引用域名里属于你的比例；**品牌提及分布**：回答里你和竞品各占多少
- **问题级诊断分型**：疑似负面 > 竞品主导 > 完全缺席 > 排名靠后，规则固定可复现
- **GEO 健康分**：提及率×30 + 引用×25 + 阵地×20 + 内容×15 + 事实×10，未测项权重归一、不编数
- 界面里能点开「这些数字怎么来的」查看完整口径，与代码同步维护

### 阵地地图：在哪建、建什么、建多少

19 个阵地按真实引用语料标注分量（引用量/平均位置/覆盖端），分 P0/P1/P2；每个阵地声明它承接哪类内容，与内容工作台双向联动——写完一篇，分发清单告诉你该铺到哪，铺完打勾，下期采样自动验证是否被引用。

![阵地地图](docs/screenshots/channels.png)

### 工单自动验收，before/after 有数

每条工单带验收标准。标「自动」的由重抓站点 + 下期采样判定，不靠人说做完了；量化工单显示「首测 → 当前 → 目标」进度条，回归了自动打回。

![行动计划](docs/screenshots/plan.png)

### 内容工作台：从选题到分发

选题池按「未提及 + 无内容」排序；写稿时左侧带必含抽取块与品牌事实，右侧实时预检可被引用度；成稿后一键发布到 GitHub / WordPress 草稿 / 公众号草稿箱 / 自定义 Webhook（发布永远手动确认）。

![内容工作台](docs/screenshots/workbench.png)

### 更多

- **站点体检**：robots/sitemap/llms.txt/抽取块六维诊断，点等级或缺块直接筛选问题页、直达修复工单
- **竞品对比**：每个对手最强的引擎一键联动到引擎表现；失守/独占问题就是选题池
- **品牌事实库**：全站唯一口径来源，llms.txt 与 JSON-LD 由它生成；AI 说法逐条人工比对
- **效果验收**：逐题前后期采样对比（分市场），任务级 before/after
- **周期复跑**：每 7/14/30 天自动跑完整一期，长期运营与月报
- **多品牌**：一个实例管多个项目，数据互相隔离

## 快速开始

```bash
git clone https://github.com/bingqiang2021/geolook.git
cd geolook
pip3 install requests beautifulsoup4 lxml   # 全部第三方依赖，就这三个

# 打开看板（引擎 Key 可在界面「设置」里配，写入本地 .env）
python3 scripts/geo.py ui                   # → http://127.0.0.1:8765

# 或者一条命令全自动
python3 scripts/geo.py new --url https://example.com --market both
```

一个 Key 都没配也能跑，只是跳过自动采样，无 API 的引擎走人工采样表（`sample-sheet` 导出、`sample-import` 回灌）。

## 命令一览

| 命令 | 作用 |
|---|---|
| `new` | ★ 只给一个网址，全自动出三份交付物 |
| `ui` | ★ 全流程界面（新建/配置/问题库/运行/工单/资产/发布/交付） |
| `serve` | 全流程一条命令；`cycle` 轻量循环（抓取→体检→采样→报告） |
| `bootstrap` | 从官网正文推导品牌事实、竞品、问题库（抽不到标「待确认」） |
| `crawl` / `audit` | 抓站 / 六维 GEO 打分 |
| `sample` | 有 API 的引擎自动采样；`sample-sheet` / `sample-import` 人工采样表 |
| `plan` | 诊断结果 → 带验收标准的结构化工单 |
| `generate` | 产出可部署资产（`--draft` 额外出 LLM 初稿） |
| `lint` | 检查 AI 初稿编造风险，交付前必跑 |
| `verify` | 重抓并自动验收工单闭环 |
| `report` / `deliverables` / `deliver` | 报告 / 三份正式交付物 / 客户交付包 |
| `publish` | 成稿发布到已配置渠道（永远手动触发） |

## 评分依据

六个维度全部锚在公开实证数据上（602 条 Prompt / 21,143 条引用 / CN-GEO 187,818 条国内去重引用），`scripts/audit.py` 是 [references/method.md](references/method.md) 的代码实现。几条最有用的：

- 高影响力页面平均 **1,943 词**，低分页仅 170 词（11.4x）
- 含数字 **+61.6%**、定义 **+57.3%**、对比 **+55.3%**、how-to **+41.2%** 被引用概率
- 纯 Q&A 排版反而 **−5.7%**——排成问答样子没用
- 对题性是最强预测因子（r = 0.432），高于权威度
- 品牌官网类信源只占国内全库引用的 **1.37%**——官网是事实源不是引用源（[references/cn-source-ranking.md](references/cn-source-ranking.md)）

## 设计原则

- **单机自托管**：标准库 `http.server`，只绑 127.0.0.1；无数据库、无账号体系，数据就是 `work/<项目>/` 下的 JSON 与 Markdown，git 一下就是备份
- **宁缺毋滥**：品牌事实只从官网正文抽取，抽不到标「待确认」；竞品严禁发明名字；AI 初稿必须过 lint 并人工核实后才能发布
- **验收即产品**：「建议」和「服务」的分界线是能不能自动验收——能自动判定的绝不靠人回填
- **发布永远手动**：渠道凭证在本地 `.env`（权限 600），每次发布必须人点击确认；公众号/WordPress 只进草稿箱，没有任何自动对外发布路径

## 与 Claude Code 集成

本仓库同时是一个 Claude Code 技能（[SKILL.md](SKILL.md)）：把仓库放进技能目录，对 Claude 说「给 example.com 做 GEO」即可驱动全流程，包括需要 LLM 判断的环节（问题库设计、内容初稿、月报解读）。不用 Claude 也完全可用——所有脚本都是普通 CLI。

## 目录结构

```
scripts/          全部逻辑（geo.py CLI 入口 · dashboard.py 看板服务 · ui.html 单页前端）
references/       方法论：采样纪律、内容模式实测、国内外平台引用结构
tests/            单元测试
work/<slug>/      每个项目的全部数据（gitignore，不出本机）
docs/screenshots/ 界面截图 · docs/demo.mp4 40 秒产品演示
```

## 产品演示

📹 [40 秒演示视频](docs/demo.mp4) · 🖼 [全部页面截图](docs/screenshots/)

## License

[MIT](LICENSE)
