# AI 流量归因：从「被引用」到「带来业务结果」

可见性指标（提及率/引用份额）说明你进了 AI 的答案；归因层回答下一个问题：
**AI 的答案有没有把人送到你的站上、这些人有没有转化。** 只看被引用不看转化，
监测就变成了汇报表演（reporting theater）。

## 归因链路

```
用户问 AI → 答案引用你 → 用户点击引用链接 → 落地页 → 注册/咨询/下单
            （采样可测）      （referrer/UTM 可测）    （事件 + 来源快照可测）
```

三段各自能测、各自会漏，**不能互相替代**：

1. **采样**测「答案里有没有你」——上游供给，GeoLook 已覆盖
2. **Referrer/UTM** 测「AI 带来了多少会话」——本文重点
3. **转化事件 + 来源快照**测「这些会话值多少钱」——落在你的业务系统里

## AI 引擎来源域名清单

配置前先在**自己的服务器日志/GA4 里核对**——各家 App 的 referrer 策略随时会变，
且 App 内打开经常不带 referrer（见下方「测的是下界」）。

| 引擎 | 常见 referrer 域名 | 备注 |
|---|---|---|
| ChatGPT | `chatgpt.com`、`chat.openai.com` | 网页版带 referrer |
| Perplexity | `perplexity.ai` | 引用点击率相对高 |
| Gemini | `gemini.google.com` | |
| Copilot | `copilot.microsoft.com`、`bing.com` | bing.com 混杂传统搜索 |
| Claude | `claude.ai` | |
| Grok | `grok.com` | |
| 豆包 | `doubao.com` | App 流量大部分无 referrer |
| Kimi | `kimi.moonshot.cn`、`kimi.com` | |
| DeepSeek | `chat.deepseek.com` | |
| 智谱清言 | `chatglm.cn` | |
| 腾讯元宝 | `yuanbao.tencent.com` | |
| 通义 | `tongyi.aliyun.com`、`tongyi.com` | |
| 文心一言 | `yiyan.baidu.com` | 百度AI搜索的点击多数仍从 `baidu.com` 来，难与传统搜索区分 |
| 秘塔 | `metaso.cn` | |
| 纳米AI | `n.cn` | |
| 夸克 | `quark.cn`、`sm.cn` | sm.cn 混杂传统搜索 |

> 未列出 ≠ 不存在。任何新引擎先抓一段自己的日志看 `Referer` 头再加进清单。

## 三条配置动作

### 1. GA4 / 分析工具：建「AI 来源」自定义渠道组

匹配条件用来源（referrer）正则，`generate --asset attribution` 会按项目市场
产出可直接粘贴的正则（`assets/attribution/`）。

### 2. 服务器日志：直接数

```bash
grep -iE "chatgpt\.com|perplexity\.ai|gemini\.google|claude\.ai|doubao\.com|kimi\.|deepseek|chatglm|yuanbao\.tencent|metaso" access.log | wc -l
```

日志比 GA4 可靠：不受前端拦截、广告屏蔽影响，还能看到 AI 爬虫自己的抓取行为
（UA 含 GPTBot / ClaudeBot / PerplexityBot——抓取变多通常先于引用变多，是个前置信号）。

### 3. 转化事件保存来源快照

归因优先级：**点击 ID > UTM > referrer > 直接/未知**。
在注册/留资/下单事件里把「首次触点 + 末次触点」的来源存进业务库（来源快照），
否则回头只能看聚合数字，没法回答「这单是不是 AI 带来的」。

## 纪律：测的是下界，不许外推

- App 内打开、隐私策略、跨设备都会吃掉 referrer——**测到的 AI 流量是下界**，
  报告里写「可归因的 AI 会话 ≥ N」，不写「AI 带来了 N」
- 各家 referrer 策略未逐一验证，清单标注为「常见」；以自己日志核对为准，核对过的才算 A 级证据
- AI 来源会话通常绝对量小、意图深——先看转化率而不是会话数，样本小于三位数时不下结论
- 不要为了归因给公开内容链接堆 UTM 参数：带参 URL 被 AI 引用后会稀释规范 URL 的引用份额。
  **UTM 只用在你完全可控且不会被引擎收录的位置**（如邮件、私域）；公开阵地靠 referrer 归因
