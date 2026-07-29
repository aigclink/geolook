# 资料索引

`method.md` 和 `cn-platforms.md` 里的数字都出自这里。**需要更深的方法细节时才来取**，
不要每次任务都全量拉——大部分场景 references 里的蒸馏版本已经够用。

---

## 数据与实证研究

| 资料 | 地址 | 什么时候用 |
|---|---|---|
| GEO Citation Lab（数据总仓） | https://github.com/yaojingang/geo-citation-lab | 要复算或查原始口径 |
| 海外跨平台实验 3 分钟速读 | `01-geo-experiment-data-report/QUICK_REPORT.md` | **最高性价比**，`method.md` 的数字主要来自这里 |
| 国内 AI 引用偏好数据集 CN-GEO | `03-cn-geo-citation-dataset/` | 查国内平台/信源分布，21.4 万条引用记录 |
| 海外 AI 引用偏好数据集 | `01-geo-experiment-data-report/` | 做海外市场时的信源判据 |
| 论文：Citation Selection → Absorption | https://arxiv.org/abs/2604.25707 | 海外三平台实验，`method.md` 第 2 节数字的出处 |
| 论文：中文生成式搜索引用什么 | https://arxiv.org/pdf/2607.15771 | 国内四产品八界面，Web/App 差异的出处 |
| **本 skill 实算的信源榜** | [`cn-source-ranking.md`](cn-source-ranking.md) | **国内信源优先级的唯一依据**，含复算脚本 |
| 54 篇 GEO/AEO 论文库 | `02-geo-aeo-ai-search-papers/` | 深度研究 |

拉取方式（GitHub 网页版可能被网络策略拦，用 git/curl）：

```bash
git clone --depth 1 https://github.com/yaojingang/geo-citation-lab.git
```

单文件取：`https://raw.githubusercontent.com/yaojingang/geo-citation-lab/main/<路径>`

---

## 方法论与工具

| 资料 | 地址 | 说明 |
|---|---|---|
| yao-geo-skills（21 个细分 skill） | https://github.com/yaojingang/yao-geo-skills | 需要某个环节的**更细方法**时去查对应 `skills/<id>/SKILL.md` |
| **GEORank**（开源 GEO 工作台） | https://github.com/yaojingang/GEORank | 见下方说明 |
| GEORankHub（官方演示站） | https://georankhub.com | 不想自建时的在线入口 |
| GEOFlow（开源 GEO 运营系统） | https://github.com/yaojingang/GEOFlow | 要上规模化内容生产/分发平台时才需要，Laravel + Docker |
| GEO 资源专题 | https://tok123.cc/collections/geo-resources-and-services | 工具与服务商索引 |

**GEORank vs 本 skill 怎么选**：

GEORank 是完整的自托管 GEO 工作台（Next.js + FastAPI + PostgreSQL/Redis/Qdrant/Neo4j/MinIO），
覆盖公司目录、网站诊断、AI 问答、方案生成、拓词工作台、JSON-LD/llms.txt 生成器、
专家与教程频道、管理后台。

- **本 skill**：命令行 + 文件，零基础设施，适合**单人或小团队跑几个项目、要可版本控制的产出**
- **GEORank**：要多人协作、对客户交付、做成产品或对外提供 GEO 服务时上它
- 两者不冲突：可以用本 skill 做诊断和监测，把结论喂给 GEORank 做内容资产管理

它的 JSON-LD 生成器、llms.txt 生成器、GEO 标题生成器可以直接拿来用，
省得手写——但**判断标准仍以 `method.md` 为准**，工具生成的结果要按六维评分复核。

**yao-geo-skills 对照表**（本 skill 的哪一步对应它的哪个包，需要展开时去读）：

| 本 skill 步骤 | 对应 yao-geo-skills |
|---|---|
| 步骤 2 建问题库 | `yao-geo-intent-miner` |
| 步骤 3 站点体检 | `yao-geo-page-audit`、`yao-geo-panorama-audit` |
| 步骤 4 出方案 | `yao-geo-execution-roadmap` |
| 步骤 5 内容生产 | `yao-geo-explainer-builder`、`yao-geo-comparison-builder`、`yao-geo-ranking-article-builder`、`yao-geo-content-refiner`、`yao-geo-title-optimizer` |
| 事实卡 / 图谱 | `yao-geo-knowledge-base-builder`、`yao-geo-brand-graph` |
| 步骤 6 监测 | `yao-geo-effect-monitor`、`yao-geo-tracking`、各平台 crawler |

---

## 报告与文章

| 资料 | 地址 |
|---|---|
| 《国内生成式AI引用生态全景报告》 | https://doc.laoyao.cn/qty18p |
| 《信源偏好分析报告》 | https://doc.laoyao.cn/krgovd |
| 《GEO白皮书》 | https://yaojingang.feishu.cn/docx/Jv85dXAeZoKJ7exJi4Yc4Edrnhf |
| 《GEO红皮书》 | https://yaojingang.feishu.cn/wiki/Otqtw0HFbiNeCMkjKalcFkoJnpf |
| 《GEO蓝皮书》 | https://yaojingang.feishu.cn/wiki/MwkiwPDqCiHGwVk2uOtcNUlrnnf |
| 《GEO到底是什么》 | https://mp.weixin.qq.com/s/GXuu0Hku-j-8ona5yzQSvA |
| 《从SEO到GEO，从流量到Agent》 | https://mp.weixin.qq.com/s/2P_zSjJkybl-rAyZjMIQAw |
| 《从AI搜索逻辑到GEOFlow落地实战》 | https://mp.weixin.qq.com/s/8Lyrzux7WacHjiHx_P9Fbg |
| 《一文讲透GEO内容工程》 | https://mp.weixin.qq.com/s/0ZZ5je2-W83HY7RtmsYkJA |

飞书文档和 doc.laoyao.cn 可能需要登录或对 WebFetch 返回 404；抓不到就让用户贴正文，别硬抓。
