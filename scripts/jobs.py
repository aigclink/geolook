"""后台任务：让界面能触发管线命令并看到实时日志。

用**子进程**而不是线程跑命令——管线里有 requests、文件写入和模块级状态，
子进程隔离最干净，也不会因为一个任务崩掉整个服务。

每个任务一份日志文件，界面轮询增量拉取。同一项目同时只允许一个任务在跑，
避免 crawl 和 verify 抢同一份 audit.json。
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import geolib as G

JOBS_DIR = G.ROOT / ".jobs"
GEO_PY = G.ROOT / "scripts" / "geo.py"

# 界面上可触发的动作。参数经过白名单，不接受任意命令。
ACTIONS: dict[str, dict] = {
    "crawl":    {"label": "抓取站点", "args": ["--max-pages"], "desc": "重新抓取官网页面"},
    "audit":    {"label": "页面体检", "args": [], "desc": "六维打分"},
    "sample":   {"label": "AI 答案采样", "args": ["--limit", "--repeat", "--platforms"],
                 "desc": "打问题库到各平台", "slow": True},
    "bootstrap":{"label": "自动推导底座", "args": ["--skip-llm"],
                 "desc": "从官网正文推出品牌事实、竞品、问题库", "slow": True},
    "deliverables":{"label": "出三份交付物", "args": [], "desc": "诊断报告 / 优化方案 / 执行方案"},
    "plan":     {"label": "生成工单", "args": [], "desc": "诊断结果 → 带验收标准的工单"},
    "expand":   {"label": "拓词扩题", "args": ["--no-llm"],
                 "desc": "下拉词扩出真实需求候选题（入库需手动勾选）"},
    "blueprint":{"label": "生成建设蓝图", "args": [], "desc": "在哪些平台建、建什么内容、覆盖度"},
    "generate": {"label": "生成资产", "args": ["--asset", "--draft", "--draft-limit"],
                 "desc": "llms.txt / JSON-LD / 片段 / 大纲"},
    "lint":     {"label": "初稿风险检查", "args": [], "desc": "查 AI 初稿的编造风险"},
    "report":   {"label": "生成报告", "args": [], "desc": "Markdown + HTML"},
    "verify":   {"label": "自动验收", "args": ["--no-recrawl"], "desc": "重抓并判定工单是否闭环",
                 "slow": True},
    "deliver":  {"label": "打包交付", "args": [], "desc": "客户交付包"},
    "sample-sheet": {"label": "导出人工采样表", "args": [], "desc": "无 API 平台用"},
    "autopilot":{"label": "全自动引导", "args": ["--no-sample", "--limit", "--skip-llm"],
                 "desc": "推导底座 → 采样 → 工单 → 资产 → 三份交付物", "slow": True},
    "serve":    {"label": "跑完整周期", "args": ["--max-pages", "--limit", "--no-sample",
                                                 "--draft", "--draft-limit"],
                 "desc": "抓取→体检→采样→工单→资产→报告→验收→交付", "slow": True},
}

FLAG_ARGS = {"--no-recrawl", "--draft", "--no-sample", "--skip-llm", "--no-llm"}  # 布尔开关，无值

_lock = threading.Lock()
_running: dict[str, str] = {}   # slug -> job_id
_procs: dict[str, subprocess.Popen] = {}


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _log_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.log"


def _write(job: dict):
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    G.write_json(_job_path(job["id"]), job)


def get(job_id: str) -> dict | None:
    p = _job_path(job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:  # noqa: BLE001  损坏的 job 文件不该把轮询打成 500
        return None


def tail(job_id: str, offset: int = 0) -> tuple[str, int]:
    """返回 (增量文本, 新 offset)。界面按 offset 轮询，不重复拉。"""
    p = _log_path(job_id)
    if not p.exists():
        return "", offset
    data = p.read_bytes()
    chunk = data[offset:]
    return chunk.decode("utf-8", "replace"), len(data)


def running_for(slug: str) -> str | None:
    with _lock:
        jid = _running.get(slug)
    if not jid:
        return None
    j = get(jid)
    return jid if j and j["status"] == "running" else None


def recent(slug: str | None = None, limit: int = 12) -> list[dict]:
    if not JOBS_DIR.exists():
        return []
    out = []
    for f in sorted(JOBS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            j = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if slug and j.get("slug") != slug:
            continue
        j.pop("cmd", None)
        out.append(j)
        if len(out) >= limit:
            break
    return out


def start(slug: str, action: str, params: dict | None = None) -> dict:
    if action not in ACTIONS:
        raise ValueError(f"不支持的动作：{action}")
    if running_for(slug):
        raise RuntimeError("该项目已有任务在运行，等它结束或先停止")

    spec = ACTIONS[action]
    cmd = [sys.executable, "-u", str(GEO_PY), action, "--slug", slug]
    for k, v in (params or {}).items():
        flag = k if k.startswith("--") else "--" + k
        if flag not in spec["args"]:
            continue
        if flag in FLAG_ARGS:
            if v:
                cmd.append(flag)
        elif v not in (None, "", []):
            cmd += [flag, str(v)]

    job = {
        "id": uuid.uuid4().hex[:12], "slug": slug, "action": action,
        "label": spec["label"], "status": "running",
        "started_at": G.now_iso(), "finished_at": None, "exit_code": None,
        "cmd": " ".join(cmd[2:]),
    }
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _write(job)
    logf = _log_path(job["id"]).open("wb")
    logf.write(f"$ geo {' '.join(cmd[3:])}\n".encode())
    logf.flush()

    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    try:
        proc = subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                                cwd=str(G.ROOT), env=env, start_new_session=True)
    except Exception as e:  # noqa: BLE001  Popen 挂了不能留下永远 running 的僵尸记录
        logf.close()
        job["status"] = "failed"
        job["error"] = f"{type(e).__name__}: {e}"
        job["finished_at"] = G.now_iso()
        _write(job)
        raise
    job["pid"] = proc.pid
    _write(job)
    with _lock:
        _running[slug] = job["id"]
        _procs[job["id"]] = proc

    def waiter():
        code = proc.wait()
        logf.close()
        j = get(job["id"]) or job
        j["status"] = "done" if code == 0 else ("stopped" if code < 0 else "failed")
        j["exit_code"] = code
        j["finished_at"] = G.now_iso()
        _write(j)
        with _lock:
            if _running.get(slug) == job["id"]:
                _running.pop(slug, None)
            _procs.pop(job["id"], None)

    threading.Thread(target=waiter, daemon=True).start()
    return job


def stop(job_id: str) -> bool:
    with _lock:
        proc = _procs.get(job_id)
    if proc:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:  # noqa: BLE001
            proc.terminate()
        return True
    # 服务重启后 _procs 是空的，按 job 文件里落的 pid 兜底杀整组
    job = get(job_id)
    pid = (job or {}).get("pid")
    if not pid or job.get("status") != "running":
        return False
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except Exception:  # noqa: BLE001
        return False
    job["status"] = "stopped"  # 本进程没有 waiter，自己回写，免得列表里永远 running
    job["finished_at"] = G.now_iso()
    _write(job)
    return True


def reap_orphans() -> int:
    """启动时回收孤儿 job：上次服务还在跑时留下的 status=running 记录，
    进程已死就回写 interrupted——不回收的话并发保护会永远挡住新项目。"""
    if not JOBS_DIR.exists():
        return 0
    reaped = 0
    for f in JOBS_DIR.glob("*.json"):
        try:
            job = json.loads(f.read_text("utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if job.get("status") != "running":
            continue
        pid = job.get("pid")
        if not pid and time.time() - f.stat().st_mtime < 60:
            continue  # start() 先落 running 再补 pid，毫秒级窗口内别误杀刚启动的 job
        alive = False
        if pid:
            try:
                os.kill(pid, 0)
                alive = True
            except ProcessLookupError:
                alive = False
            except PermissionError:
                alive = True
        if alive:
            continue
        job["status"] = "interrupted"
        job["finished_at"] = G.now_iso()
        _write(job)
        reaped += 1
    if reaped:
        G.info(f"回收了 {reaped} 个中断的任务记录")
    return reaped
