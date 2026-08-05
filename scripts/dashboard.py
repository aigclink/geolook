"""可观测看板：GEO 是周期性工作，关键信息是「这一期相对上一期变了什么」。

  python3 scripts/geo.py ui            # 起服务并打开浏览器

服务本身只用标准库 http.server，但顶层 import geolib 需要第三方依赖
（requests / beautifulsoup4 / lxml），缺失时会给出安装提示。
前端是 scripts/ui.html 单页应用，数据走 /api，
工单状态可以直接在界面上改（写回 tasks.json）。
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

try:
    import geolib as G
except ModuleNotFoundError as e:
    raise SystemExit(f"缺少依赖：{e.name}。请先 pip3 install requests beautifulsoup4 lxml") from e
import jobs as J
import tasks as T

UI = Path(__file__).resolve().parent / "ui.html"


# ---------------------------------------------------------------- 数据聚合

def list_projects() -> list[dict]:
    out = []
    if not G.WORK.exists():
        return out
    for d in sorted(G.WORK.iterdir()):
        cfg_path = d / "geo.json"
        if not cfg_path.exists():
            continue
        cfg = G.read_json(cfg_path, {})
        audit = G.read_json(d / "audit.json", {})
        td = G.read_json(d / "tasks.json", {})
        s = td.get("summary", {})
        out.append({
            "slug": d.name,
            "name": cfg.get("brand", {}).get("name", d.name),
            "site": cfg.get("brand", {}).get("site", ""),
            "market": cfg.get("market", "cn"),
            "avg_score": audit.get("avg_score"),
            "pages": audit.get("page_count"),
            "tasks_total": s.get("total", 0),
            "tasks_done": s.get("by_status", {}).get("done", 0),
            "p0_open": sum(1 for t in td.get("tasks", [])
                           if t["priority"] == "P0" and t["status"] != "done"),
        })
    return out


def project(slug: str) -> dict:
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    audit = G.read_json(pdir / "audit.json", {})
    td = G.read_json(pdir / "tasks.json", {"tasks": [], "summary": {}})

    verify_hist = []
    vdir = pdir / "verify"
    import verify as V
    for f in sorted(vdir.glob("*.json"), key=V.report_key) if vdir.exists() else []:
        v = G.read_json(f, {})
        rs = v.get("results", [])
        verify_hist.append({
            "date": (v.get("verified_at") or f.stem)[:10],
            "pass": sum(1 for r in rs if r["verdict"] == "通过"),
            "fail": sum(1 for r in rs if r["verdict"] == "未达标"),
            "manual": sum(1 for r in rs if r["verdict"] == "待人工"),
            "avg_score": v.get("audit_avg_score"),
        })

    deliveries = sorted((d.name for d in (pdir / "delivery").iterdir() if d.is_dir()),
                        reverse=True) if (pdir / "delivery").exists() else []

    lint = G.read_json(pdir / "assets" / "drafts" / "_lint.json", None)

    # 成稿发布状态：content/ 里的每篇成稿 ↔ publish.json 的成功记录。
    # 行动计划页的「成稿发布」卡和问题库的「已发布」标记都吃这份数据。
    content_pub = []
    cdir = pdir / "content"
    if cdir.exists():
        import re as _re
        pub_by_path: dict[str, list] = {}
        for r in G.read_json(pdir / "publish.json", []) or []:
            if r.get("ok"):
                pub_by_path.setdefault(r.get("path", ""), []).append(
                    {"platform": r.get("platform"), "platform_name": r.get("platform_name"),
                     "url": r.get("url", ""), "at": r.get("at", "")})
        for f in sorted(cdir.glob("*.md")):
            if f.name == "facts.md":
                continue
            head = f.read_text("utf-8", "replace")[:800]
            m = _re.search(r"(?m)^#\s*(.+)$", head)
            content_pub.append({
                "path": f.name,
                "title": (m.group(1).strip() if m else f.name)[:80],
                "qids": _re.findall(r"\bq\d{3}\b", head),
                "published": pub_by_path.get(f"content/{f.name}", []),
            })

    return {
        "slug": slug,
        "brand": cfg.get("brand", {}),
        "market": cfg.get("market", "cn"),
        "audit": {"avg_score": audit.get("avg_score"), "page_count": audit.get("page_count"),
                  "grade_distribution": audit.get("grade_distribution", {}),
                  "language_coverage": audit.get("language_coverage", {}),
                  "site": audit.get("site", {}), "site_issues": audit.get("site_issues", []),
                  "layers": audit.get("layers", []),
                  "block_gap": audit.get("block_gap", []),
                  "pages": sorted(audit.get("pages", []), key=lambda p: p["score"])[:40]},
        "tasks": td.get("tasks", []),
        "verify_history": verify_hist,
        "deliveries": deliveries,
        "lint": {"total": (lint or {}).get("total_issues", 0), "high": (lint or {}).get("high", 0)},
        "content_pub": content_pub,
        "blueprint": G.read_json(pdir / "blueprint.json", None),
        "distribution": G.read_json(pdir / "distribution.json", {}),
        "question_count": len(cfg.get("questions", [])),
        "deliverables_files": sorted(f.name for f in (pdir / "deliverables").glob("*.html"))
                              if (pdir / "deliverables").exists() else [],
        "analytics": _analytics(slug),
        "facts_struct": _facts_struct(slug),
    }


def _facts_struct(slug: str):
    try:
        import generate
        f = generate.parse_facts(slug)
        f.pop("raw", None)
        return f
    except Exception:  # noqa: BLE001
        return {}


def workbench(slug: str, qid: str) -> dict:
    """内容工作台：定位某个问题现有的内容/草稿/大纲文件。"""
    pdir = G.project_dir(slug)
    cfg = G.load_config(slug)
    q = next((x for x in cfg.get("questions", []) if x.get("id") == qid), None)
    sources = []
    cdir = pdir / "content"
    if cdir.exists():
        for f in sorted(cdir.glob("*.md")):
            if qid and qid in f.read_text("utf-8", "replace")[:800]:
                sources.append({"kind": "content", "path": f.name})
    for kind, sub in (("draft", "drafts"), ("outline", "outlines")):
        f = pdir / "assets" / sub / f"{qid}.md"
        if f.exists():
            sources.append({"kind": kind, "path": f"{sub}/{qid}.md"})
    return {"question": q, "sources": sources}


def _analytics(slug: str):
    try:
        import analytics
        return analytics.build(slug)
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ---------------------------------------------------------------- HTTP

def asset_tree(slug: str) -> list[dict]:
    """资产目录，供界面预览。只列文本类文件。"""
    adir = G.project_dir(slug) / "assets"
    out = []
    if not adir.exists():
        return out
    for f in sorted(adir.rglob("*")):
        if f.is_file() and f.suffix in (".txt", ".json", ".html", ".md"):
            rel = f.relative_to(adir).as_posix()
            out.append({"path": rel, "size": f.stat().st_size,
                        "group": rel.split("/")[0] if "/" in rel else "根目录"})
    return out


def read_asset(slug: str, rel: str) -> dict:
    base = (G.project_dir(slug) / "assets").resolve()
    target = (base / rel).resolve()
    try:
        target.relative_to(base)
    except ValueError:
        raise PermissionError(rel) from None
    if not target.is_file():
        raise FileNotFoundError(rel)
    return {"path": rel, "text": target.read_text("utf-8", "replace")}


def write_env(updates: dict[str, str]):
    """更新项目根目录 .env：值为空表示删除该行。同步进当前进程环境，让界面立即生效；
    任务子进程每次启动都重读 .env，天然生效。"""
    path = G.ROOT / ".env"
    lines = path.read_text("utf-8").splitlines() if path.exists() else []
    for k, v in updates.items():
        pat = re.compile(rf"\s*(export\s+)?{re.escape(k)}\s*=")
        lines = [ln for ln in lines if not pat.match(ln)]
        if v:
            lines.append(f"{k}={v}")
            os.environ[k] = v
        else:
            os.environ.pop(k, None)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), "utf-8")
    try:
        path.chmod(0o600)  # 密钥文件不给同机其他用户读
    except OSError:
        pass


def create_project(url: str, name: str, slug: str, market: str, max_pages: int) -> dict:
    import geo as CLI

    class A:  # 复用 CLI 的 init 逻辑，避免两份实现漂移
        pass
    a = A()
    a.url, a.name, a.slug, a.market, a.max_pages = url, name or None, slug or None, market, max_pages
    a.force = False          # 界面永不覆盖已有项目
    return CLI.cmd_init(a)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):  # 静音访问日志
        pass

    def _send(self, code, body: bytes, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    # ------------------------------------------------------------ GET
    def do_GET(self):
        u = urlparse(self.path)
        p, q = unquote(u.path), parse_qs(u.query)
        try:
            if p in ("/", "/index.html"):
                return self._send(200, UI.read_bytes(), "text/html; charset=utf-8")
            if p == "/api/projects":
                return self._json(list_projects())
            if p == "/api/actions":
                return self._json(J.ACTIONS)
            if p.startswith("/api/p/"):
                return self._json(project(p[len("/api/p/"):]))
            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                return self._json(G.read_json(G.project_dir(slug) / "geo.json", {}))
            if p.startswith("/api/facts/"):
                slug = p[len("/api/facts/"):]
                f = G.project_dir(slug) / "content" / "facts.md"
                return self._json({"exists": f.exists(),
                                   "text": f.read_text("utf-8") if f.exists() else ""})
            if p.startswith("/api/assets/"):
                return self._json(asset_tree(p[len("/api/assets/"):]))
            if p.startswith("/api/asset/"):
                slug = p[len("/api/asset/"):]
                return self._json(read_asset(slug, q.get("path", [""])[0]))
            if p.startswith("/api/workbench/"):
                slug = p[len("/api/workbench/"):]
                return self._json(workbench(slug, q.get("qid", [""])[0]))
            if p.startswith("/api/samples/"):
                import sample as S
                slug = p[len("/api/samples/"):]
                return self._json(S.list_samples(
                    slug, date=q.get("date", [""])[0], platform=q.get("platform", [""])[0],
                    qid=q.get("qid", [""])[0], flag=q.get("flag", [""])[0],
                    limit=int(q.get("limit", ["300"])[0])))
            if p.startswith("/api/sample/"):
                import sample as S
                slug = p[len("/api/sample/"):]
                r = S.get_sample(slug, q.get("key", [""])[0])
                return self._json(r or {"error": "找不到该样本"}, 200 if r else 404)
            if p.startswith("/api/collect/queue/"):
                # 浏览器插件的采样队列：按意图分组挑题 + 需人工采的平台
                import sample as S
                slug = p[len("/api/collect/queue/"):]
                cfg = G.load_config(slug)
                limit = int(q.get("limit", ["20"])[0])
                intent = q.get("intent", [""])[0]
                picked = [g for g in (q.get("groups", [""])[0] or "").split(",") if g.strip()]
                if not picked and intent == "buyer":
                    picked = sorted(S.BUYER_GROUPS)
                allq = cfg.get("questions", [])
                qs = [x for x in allq if not picked or x.get("group") in picked][:limit]
                counts: dict[str, int] = {}
                for x in allq:
                    g2 = x.get("group") or "未分组"
                    counts[g2] = counts.get(g2, 0) + 1
                groups = [{"name": g2, "count": c,
                           "buyer": g2 in S.BUYER_GROUPS} for g2, c in
                          sorted(counts.items(), key=lambda kv: -kv[1])]
                plats = [{"code": c, "label": lb, "market": mk}
                         for c, (lb, mk) in S.MANUAL_ONLY.items()]
                plats += [{"code": c, "label": s2["name"], "market": s2["market"]}
                          for c, s2 in S.PROVIDERS.items() if not S.available(c)]
                return self._json({"slug": slug, "brand": cfg.get("brand", {}).get("name", ""),
                                   "questions": qs, "platforms": plats,
                                   "groups": groups, "selected": picked})
            if p == "/api/keys":
                import sample as S
                rows = []
                for code, spec in S.PROVIDERS.items():
                    key = os.environ.get(spec["key_env"], "")
                    menv = spec.get("model_env")
                    rows.append({"code": code, "label": spec["name"], "market": spec["market"],
                                 "search": spec.get("search", False), "env": spec["key_env"],
                                 "ok": S.available(code),
                                 "key_tail": key[-4:] if len(key) >= 8 else "",
                                 "model": os.environ.get(menv) or spec.get("model", "") if menv else spec.get("model", ""),
                                 "model_env": menv,
                                 "model_set": bool(menv and os.environ.get(menv)),
                                 "note": spec.get("note", "")})
                for code, (label, mk) in S.MANUAL_ONLY.items():
                    rows.append({"code": code, "label": label, "market": mk,
                                 "search": True, "env": None, "ok": None})
                return self._json(rows)
            if p.startswith("/api/factcheck/"):
                slug = p[len("/api/factcheck/"):]
                return self._json(G.read_json(G.project_dir(slug) / "factcheck.json", []) or [])
            if p.startswith("/api/expand/"):
                slug = p[len("/api/expand/"):]
                return self._json(G.read_json(G.project_dir(slug) / "expand.json", {}) or {})
            if p.startswith("/api/publish/"):
                import publish as P
                slug = p[len("/api/publish/"):]
                pubs = []
                for code, spec in P.PUBLISHERS.items():
                    cfg = P._cfg(slug, code)
                    pubs.append({"code": code, "name": spec["name"], "note": spec["note"],
                                 "market": spec.get("market", "general"),
                                 "env": spec["env"], "missing": P.missing_env(code),
                                 "cfg": [{"key": k, "hint": h, "value": cfg.get(k, "")}
                                         for k, h in spec["cfg"]]})
                return self._json({"publishers": pubs, "records": P.records(slug)})
            if p.startswith("/api/content/"):
                slug = p[len("/api/content/"):]
                base = (G.project_dir(slug) / "content").resolve()
                rel = q.get("path", [""])[0]
                if rel:
                    target = (base / rel).resolve()
                    try:
                        target.relative_to(base)
                    except ValueError:
                        return self._json({"error": "非法路径"}, 403)
                    if not target.is_file():
                        return self._json({"error": "文件不存在"}, 404)
                    return self._json({"path": rel, "text": target.read_text("utf-8", "replace")})
                files = sorted(f.name for f in base.glob("*.md")) if base.exists() else []
                return self._json({"files": files})
            if p == "/api/jobs":
                slug = q.get("slug", [None])[0]
                return self._json({"jobs": J.recent(slug),
                                   "running": J.running_for(slug) if slug else None})
            if p.startswith("/api/job/"):
                jid = p[len("/api/job/"):]
                job = J.get(jid)
                if not job:
                    return self._json({"error": "job not found"}, 404)
                try:
                    off = int(q.get("offset", ["0"])[0])
                except ValueError:
                    return self._json({"error": "offset 必须是整数"}, 400)
                text, new_off = J.tail(jid, off)
                return self._json({"job": job, "log": text, "offset": new_off})
            if p.startswith("/api/files/"):
                slug = p[len("/api/files/"):]
                pdir = G.project_dir(slug)
                def ls(sub, pat="*"):
                    d = pdir / sub
                    return sorted((x.name for x in d.glob(pat)), reverse=True) if d.exists() else []
                dv = pdir / "deliverables"
                return self._json({
                    "reports": [d for d in ls("reports") if d.startswith("2")],
                    "deliveries": [d for d in ls("delivery") if d.startswith("2")],
                    "samples": ls("samples", "*.md"),
                    "deliverables": sorted(f.name for f in dv.glob("*.html")) if dv.exists() else [],
                    "content": sorted(f.name for f in (pdir / "content").glob("*.md"))
                               if (pdir / "content").exists() else [],
                })
            if p.startswith("/files/"):
                rel = p[len("/files/"):]
                target = (G.WORK / rel).resolve()
                try:
                    target.relative_to(G.WORK.resolve())
                except ValueError:
                    return self._send(403, b"forbidden", "text/plain")
                if not target.is_file():
                    return self._send(404, b"not found", "text/plain")
                ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/json",):
                    ctype += "; charset=utf-8"
                return self._send(200, target.read_bytes(), ctype)
            return self._send(404, b"not found", "text/plain")
        except FileNotFoundError:
            return self._json({"error": "文件不存在"}, 404)
        except PermissionError:
            return self._json({"error": "非法路径"}, 403)
        except SystemExit:
            return self._json({"error": "项目不存在"}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    # ------------------------------------------------------------ POST
    def do_POST(self):
        p = unquote(urlparse(self.path).path)
        try:
            body = self._body()

            if p == "/api/task":
                missing = [k for k in ("slug", "id", "status") if k not in body]
                if missing:
                    return self._json({"error": f"缺参数：{', '.join(missing)}"}, 400)
                valid = ("todo", "doing", "done", "blocked", "wontfix")  # 与 tasks.py 汇总口径一致
                if body["status"] not in valid:
                    return self._json({"ok": False, "error": f"非法状态：{body['status']}",
                                       "valid": list(valid)}, 400)
                try:
                    t = T.set_status(body["slug"], body["id"], body["status"], body.get("note", ""))
                except KeyError as e:
                    return self._json({"error": e.args[0] if e.args else str(e)}, 404)
                return self._json({"ok": True, "task": t})

            if p == "/api/init":
                url = (body.get("url") or "").strip()
                if not url:
                    return self._json({"ok": False, "error": "请填写官网地址"}, 400)
                cfg = create_project(url, body.get("name", ""), body.get("slug", ""),
                                     body.get("market", "cn"), int(body.get("max_pages", 25)))
                return self._json({"ok": True, "slug": cfg["slug"]})

            if p == "/api/run":
                job = J.start(body["slug"], body["action"], body.get("params") or {})
                return self._json({"ok": True, "job": job})

            if p.startswith("/api/sample/"):
                import sample as S
                slug = p[len("/api/sample/"):]
                key = body.get("key") or ""
                if not key:
                    return self._json({"ok": False, "error": "缺少 key"}, 400)
                res = S.patch_sample(slug, key, body.get("patch") or {})
                return self._json(res, 200 if res.get("ok") else 400)

            if p.startswith("/api/collect/"):
                # 浏览器插件回传样本。服务只绑 127.0.0.1，来源即本机用户。
                import sample as S
                slug = p[len("/api/collect/"):]
                records = body.get("records")
                if not isinstance(records, list) or not records:
                    return self._json({"ok": False, "error": "records 必须是非空数组"}, 400)
                if len(records) > 200:
                    return self._json({"ok": False, "error": "单次最多 200 条"}, 400)
                with G.project_lock(slug):
                    res = S.collect_import(slug, records)
                return self._json(res, 200 if res.get("ok") else 400)

            if p.startswith("/api/job/") and p.endswith("/stop"):
                jid = p[len("/api/job/"):-len("/stop")]
                return self._json({"ok": J.stop(jid)})

            if p.startswith("/api/config/"):
                slug = p[len("/api/config/"):]
                cur = G.read_json(G.project_dir(slug) / "geo.json", {})
                cur.update(body)          # 整体覆盖字段，前端传完整对象
                G.save_config(slug, cur)
                return self._json({"ok": True})

            if p.startswith("/api/facts/"):
                slug = p[len("/api/facts/"):]
                f = G.project_dir(slug) / "content" / "facts.md"
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p.startswith("/api/asset/"):
                slug = p[len("/api/asset/"):]
                base = (G.project_dir(slug) / "assets").resolve()
                target = (base / body["path"]).resolve()
                try:
                    target.relative_to(base)
                except ValueError:
                    return self._json({"ok": False, "error": "非法路径"}, 403)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p == "/api/precheck":
                import analytics
                return self._json(analytics.precheck(body.get("text", "")))

            if p.startswith("/api/factcheck/"):
                slug = p[len("/api/factcheck/"):]
                items = body.get("items")
                if not isinstance(items, list):
                    return self._json({"ok": False, "error": "items 必须是数组"}, 400)
                G.write_json(G.project_dir(slug) / "factcheck.json", items)
                return self._json({"ok": True, "count": len(items)})

            if p.startswith("/api/content/"):
                slug = p[len("/api/content/"):]
                base = (G.project_dir(slug) / "content").resolve()
                rel = (body.get("path") or "").strip()
                # 文件名允许中文（现有成稿即中文名），只挡路径分隔符和隐藏文件；
                # 问题归属靠文件头的 qid 注释识别，不靠文件名
                if ("/" in rel or "\\" in rel or ".." in rel or rel.startswith(".")
                        or not rel.endswith(".md") or len(rel) <= 3):
                    return self._json({"ok": False, "error": "文件名须是 .md，不能包含路径"}, 400)
                base.mkdir(parents=True, exist_ok=True)
                (base / rel).write_text(body.get("text", ""), "utf-8")
                return self._json({"ok": True})

            if p == "/api/keys":
                import publish as P
                import sample as S
                allowed = set()
                for spec in S.PROVIDERS.values():
                    allowed.add(spec["key_env"])
                    if spec.get("model_env"):
                        allowed.add(spec["model_env"])
                for spec in P.PUBLISHERS.values():
                    allowed.update(spec["env"])
                updates = body.get("updates")
                if not isinstance(updates, dict) or not updates:
                    return self._json({"ok": False, "error": "updates 必须是非空对象"}, 400)
                bad = [k for k in updates if k not in allowed]
                if bad:
                    return self._json({"ok": False,
                                       "error": f"不允许的变量：{', '.join(bad)}"}, 400)
                clean = {k: str(v or "").strip() for k, v in updates.items()}
                if any("\n" in v or "\r" in v for v in clean.values()):
                    return self._json({"ok": False, "error": "值不能包含换行"}, 400)
                write_env(clean)
                return self._json({"ok": True})

            if p.startswith("/api/publishcfg/"):
                import publish as P
                slug = p[len("/api/publishcfg/"):]
                code = body.get("platform")
                if code not in P.PUBLISHERS:
                    return self._json({"ok": False, "error": f"未知渠道 {code}"}, 400)
                keys = {k for k, _ in P.PUBLISHERS[code]["cfg"]}
                cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                pub = cfg.setdefault("publishing", {})
                pub[code] = {k: str(v or "").strip() for k, v in (body.get("cfg") or {}).items()
                             if k in keys}
                G.save_config(slug, cfg)
                return self._json({"ok": True})

            if p.startswith("/api/publish/"):
                # 发布 = 外发动作：只响应界面上用户的明确点击，服务端绝不自行调用
                import publish as P
                slug = p[len("/api/publish/"):]
                r = P.publish(slug, body.get("platform", ""), body.get("path", ""),
                              body.get("title", ""))
                return self._json(r, 200 if r.get("ok") else 400)

            if p.startswith("/api/distribution/"):
                # 分发打勾：记录某问题的内容已铺到某阵地（人工确认口径，非自动判定）
                slug = p[len("/api/distribution/"):]
                qid, ch = (body.get("qid") or "").strip(), (body.get("channel") or "").strip()
                if not qid or not ch:
                    return self._json({"ok": False, "error": "缺 qid / channel"}, 400)
                path = G.project_dir(slug) / "distribution.json"
                dist = G.read_json(path, {})
                if body.get("on"):
                    dist.setdefault(qid, {})[ch] = G.now_iso()
                else:
                    dist.get(qid, {}).pop(ch, None)
                    if not dist.get(qid):
                        dist.pop(qid, None)
                G.write_json(path, dist)
                return self._json({"ok": True, "distribution": dist})

            if p == "/api/questions-add":
                slug = body.get("slug") or ""
                items = body.get("items")
                if not slug or not isinstance(items, list) or not items:
                    return self._json({"ok": False, "error": "缺 slug / items"}, 400)
                cfg = G.read_json(G.project_dir(slug) / "geo.json", {})
                qs = cfg.setdefault("questions", [])
                existing = {q.get("text", "").strip() for q in qs}
                series = {"cn": 1, "global": 101, "both": 901}
                used = {int(m.group(1)) for q in qs
                        if (m := re.match(r"q(\d+)$", str(q.get("id", ""))))}
                added = []
                for it in items:
                    text = str(it.get("text") or "").strip()
                    mk = it.get("market") if it.get("market") in series else "cn"
                    grp = str(it.get("group") or "场景").strip() or "场景"
                    if not text or text in existing:
                        continue
                    n = series[mk]
                    while n in used:
                        n += 1
                    used.add(n)
                    q = {"id": f"q{n:03d}", "group": grp, "market": mk, "text": text,
                         "source": "expand"}
                    qs.append(q)
                    existing.add(text)
                    added.append(q)
                if added:
                    G.save_config(slug, cfg)
                return self._json({"ok": True, "added": len(added),
                                   "ids": [q["id"] for q in added]})

            if p == "/api/sample-import":
                import sample as S
                path = G.project_dir(body["slug"]) / "samples" / body["file"]
                if body.get("text") is not None:
                    path.write_text(body["text"], "utf-8")
                S.sample_import(body["slug"], str(path))
                return self._json({"ok": True})

            return self._send(404, b"not found", "text/plain")
        except SystemExit:  # G.die 会 sys.exit
            return self._json({"ok": False, "error": "操作失败（常见原因：项目标识已被占用）"}, 400)
        except (ValueError, RuntimeError) as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)


def _monitor_tick():
    """周期复跑：geo.json 的 monitor.next_run 到期就自动跑完整一期。

    GEO 是周期性工作——只在看板服务运行时触发（单机自托管，没有独立守护进程），
    服务停着的那几天不补跑，到期后下次启动时跑一次。"""
    for d in (G.WORK.iterdir() if G.WORK.exists() else []):
        cfg_path = d / "geo.json"
        if not cfg_path.exists():
            continue
        cfg = G.read_json(cfg_path, {})
        mon = cfg.get("monitor") or {}
        every = mon.get("every_days")
        if not every or (mon.get("next_run") or "") > G.today():
            continue
        if J.running_for(d.name):
            continue  # 有任务在跑，下个 tick 再看
        try:
            J.start(d.name, "serve", {})
            mon["next_run"] = (date.today() + timedelta(days=int(every))).isoformat()
            cfg["monitor"] = mon
            G.save_config(d.name, cfg)
            G.info(f"周期复跑触发：{d.name}，下次 {mon['next_run']}")
        except (ValueError, RuntimeError) as e:
            G.info(f"周期复跑跳过 {d.name}：{e}")


def _monitor_loop():
    while True:
        try:
            _monitor_tick()
        except Exception as e:  # noqa: BLE001  调度线程绝不能死
            G.info(f"周期复跑检查出错：{type(e).__name__}: {e}")
        time.sleep(1800)


def run(port: int = 8765, open_browser: bool = True):
    J.reap_orphans()  # 回收上次服务留下的 running 僵尸记录，恢复并发保护
    threading.Thread(target=_monitor_loop, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    G.info(f"看板已启动：{url}（Ctrl+C 退出）")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        G.info("看板已停止")
    finally:
        srv.server_close()
