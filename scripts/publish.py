"""发布渠道对接：把成稿/资产一键发到你自己的渠道，并留发布记录。

安全边界（刻意为之，别放松）：
- 凭证只放项目根目录 .env（与引擎 Key 同一套管理，界面可配，已 gitignore）；
- 发布动作只由界面上的明确点击或 CLI 显式命令触发，没有任何自动发布路径；
- 公众号只建草稿（后台人工预览群发）；WordPress 只建草稿文章；
- GitHub 是提交文件到你自己的仓库；Webhook 打到你自己配置的接收端。

发布记录写 work/<slug>/publish.json，效果验收的 external.any 检查器
可以用发布落点的域名做「已被引擎引用」判定，闭环到验收。
"""

from __future__ import annotations

import base64
import json
import os
import re

import requests

import geolib as G

# 渠道注册表：env 是 .env 里的凭证变量；cfg 是存在项目 geo.json publishing.<code> 的非敏感配置
PUBLISHERS = {
    "github": {
        "name": "GitHub 仓库", "env": ["GITHUB_TOKEN"],
        "cfg": [("repo", "owner/repo"), ("branch", "main"), ("dir", "docs/geo")],
        "note": "Contents API 提交 markdown 到你的仓库（配 Pages/静态站即上线）",
    },
    "wordpress": {
        "name": "WordPress", "env": ["WP_USER", "WP_APP_PASSWORD"],
        "cfg": [("site_url", "https://blog.example.com")],
        "note": "REST API 新建草稿文章，登录后台确认后再发布",
    },
    "wechat_draft": {
        "name": "公众号草稿箱", "env": ["WECHAT_APPID", "WECHAT_APPSECRET"],
        "cfg": [("thumb_media_id", "永久素材封面 media_id（草稿必需）")],
        "note": "新建草稿，需在公众号后台预览并群发；服务器 IP 要在白名单",
    },
    "webhook": {
        "name": "自定义 Webhook", "env": ["PUBLISH_WEBHOOK_URL"],
        "cfg": [],
        "note": "POST JSON {title, markdown, html, slug, path} 到你自己的接收端",
    },
}


def missing_env(code: str) -> list[str]:
    return [e for e in PUBLISHERS[code]["env"] if not os.environ.get(e)]


def _cfg(slug: str, code: str) -> dict:
    return (G.load_config(slug).get("publishing") or {}).get(code) or {}


# ---------------------------------------------------------------- markdown → html
# 公众号/WordPress 要 HTML。只做最小转换（标题/加粗/链接/列表/代码块/段落），
# 不引第三方库；表格等复杂结构原样进 <p>，发布前在渠道后台肉眼过一遍。

def md2html(md: str) -> str:
    md = re.sub(r"<!--.*?-->", "", md, flags=re.S)
    out, in_code, in_list = [], False, False

    def inline(s):
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', s)
        return s

    for line in md.splitlines():
        if line.strip().startswith("```"):
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(line.replace("&", "&amp;").replace("<", "&lt;"))
            continue
        m = re.match(r"(#{1,6})\s+(.*)", line)
        li = re.match(r"\s*[-*]\s+(.*)", line) or re.match(r"\s*\d+[.、]\s+(.*)", line)
        if in_list and not li:
            out.append("</ul>")
            in_list = False
        if m:
            n = min(len(m.group(1)) + 1, 6)  # 文内 # 降一级，标题留给渠道的 title 字段
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif li:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(li.group(1))}</li>")
        elif line.strip():
            out.append(f"<p>{inline(line.strip())}</p>")
    if in_list:
        out.append("</ul>")
    if in_code:
        out.append("</code></pre>")
    return "\n".join(out)


# ---------------------------------------------------------------- 各渠道实现

def _pub_github(cfg, text, title, fname):
    repo, branch = cfg.get("repo", ""), cfg.get("branch", "main")
    if not repo or "/" not in repo:
        return {"ok": False, "error": "先在设置里配置 repo（owner/repo）"}
    path = (cfg.get("dir", "").strip("/") + "/" + fname).lstrip("/")
    H = {"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
         "Accept": "application/vnd.github+json"}
    url = f"https://api.github.com/repos/{repo}/contents/{path}"
    body = {"message": f"geo: publish {title}", "branch": branch,
            "content": base64.b64encode(text.encode()).decode()}
    r0 = requests.get(url, headers=H, params={"ref": branch}, timeout=30)
    if r0.status_code == 200:  # 已存在→更新
        body["sha"] = r0.json().get("sha")
    r = requests.put(url, headers=H, json=body, timeout=30)
    if r.status_code in (200, 201):
        return {"ok": True, "url": r.json().get("content", {}).get("html_url", "")}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_wordpress(cfg, text, title, fname):
    site = (cfg.get("site_url") or "").rstrip("/")
    if not site:
        return {"ok": False, "error": "先在设置里配置 site_url"}
    r = requests.post(f"{site}/wp-json/wp/v2/posts",
                      auth=(os.environ["WP_USER"], os.environ["WP_APP_PASSWORD"]),
                      json={"title": title, "content": md2html(text), "status": "draft"},
                      timeout=30)
    if r.status_code == 201:
        return {"ok": True, "url": r.json().get("link", ""),
                "note": "已建为草稿，到 WordPress 后台确认发布"}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


def _pub_wechat(cfg, text, title, fname):
    thumb = cfg.get("thumb_media_id", "")
    if not thumb:
        return {"ok": False, "error": "缺封面：先在设置里配置 thumb_media_id（永久素材）"}
    tr = requests.get("https://api.weixin.qq.com/cgi-bin/token",
                      params={"grant_type": "client_credential",
                              "appid": os.environ["WECHAT_APPID"],
                              "secret": os.environ["WECHAT_APPSECRET"]}, timeout=30).json()
    tok = tr.get("access_token")
    if not tok:
        return {"ok": False, "error": f"取 token 失败：{tr.get('errmsg', tr)}"}
    art = {"title": title[:60], "content": md2html(text), "thumb_media_id": thumb,
           "digest": re.sub(r"\s+", " ", text)[:100]}
    r = requests.post(f"https://api.weixin.qq.com/cgi-bin/draft/add?access_token={tok}",
                      data=json.dumps({"articles": [art]}, ensure_ascii=False).encode(),
                      timeout=30).json()
    if r.get("media_id"):
        return {"ok": True, "url": "", "note": "已进草稿箱，到公众号后台预览群发"}
    return {"ok": False, "error": f"draft/add 失败：{r.get('errmsg', r)}"}


def _pub_webhook(cfg, text, title, fname):
    r = requests.post(os.environ["PUBLISH_WEBHOOK_URL"],
                      json={"title": title, "markdown": text, "html": md2html(text),
                            "path": fname}, timeout=30)
    if 200 <= r.status_code < 300:
        url = ""
        try:
            url = (r.json() or {}).get("url", "")
        except Exception:  # noqa: BLE001  接收端不回 JSON 也算成功
            pass
        return {"ok": True, "url": url}
    return {"ok": False, "error": f"HTTP {r.status_code}: {r.text[:200]}"}


_IMPL = {"github": _pub_github, "wordpress": _pub_wordpress,
         "wechat_draft": _pub_wechat, "webhook": _pub_webhook}


# ---------------------------------------------------------------- 入口与记录

def _read_source(slug: str, rel: str) -> tuple[str, str]:
    """rel 限定在 content/ 或 assets/ 下，返回 (文本, 文件名)。

    校验解析后的真实路径归属，防 content/../ 这类穿越。"""
    pdir = G.project_dir(slug).resolve()
    target = (pdir / rel).resolve()
    if not any(target.is_relative_to(pdir / d) for d in ("content", "assets")):
        raise ValueError("只允许发布 content/ 或 assets/ 下的文件")
    return target.read_text("utf-8"), target.name


def _title_of(text: str, fname: str) -> str:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return m.group(1).strip() if m else fname.rsplit(".", 1)[0]


def records(slug: str) -> list[dict]:
    return G.read_json(G.project_dir(slug) / "publish.json", []) or []


def publish(slug: str, code: str, rel: str, title: str = "") -> dict:
    if code not in PUBLISHERS:
        return {"ok": False, "error": f"未知渠道 {code}"}
    miss = missing_env(code)
    if miss:
        return {"ok": False, "error": "缺凭证：" + "、".join(miss)}
    try:
        text, fname = _read_source(slug, rel)
    except (ValueError, FileNotFoundError):
        return {"ok": False, "error": f"文件不可用：{rel}"}
    title = title or _title_of(text, fname)
    res = _IMPL[code](_cfg(slug, code), text, title, fname)
    entry = {"at": G.now_iso(), "platform": code, "platform_name": PUBLISHERS[code]["name"],
             "path": rel, "title": title, "ok": res.get("ok", False),
             "url": res.get("url", ""), "note": res.get("note", ""),
             "error": res.get("error", "")}
    rows = records(slug)
    rows.append(entry)
    G.write_json(G.project_dir(slug) / "publish.json", rows[-200:])
    return {**res, "record": entry}
