import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import deliver as DL
import report as R


def _task(tid="T-001"):
    return {"id": tid, "priority": "P0", "package": "技术底座", "market": "cn",
            "title": "修标题", "why": "w", "action": "a", "owner": "开发",
            "effort": "S", "window": "30 天", "status": "todo",
            "acceptance": {"type": "auto", "desc": "d"}, "affected": []}


TASKS = {"tasks": [_task()],
         "summary": {"total": 1, "auto_verifiable": 1,
                     "by_priority": {"P0": 1, "P1": 0, "P2": 0},
                     "by_status": {"todo": 1}}}


def _project(d, slug="x", audit_date=None, verify_date=None, report_dirs=()):
    """建最小可用项目：audit/tasks 必备，verify/reports 按参数给。"""
    pdir = Path(d) / slug
    pdir.mkdir(parents=True)
    (pdir / "geo.json").write_text(json.dumps(
        {"brand": {"name": "X", "site": "https://x.com"}, "market": "cn"},
        ensure_ascii=False), "utf-8")
    G.write_json(pdir / "audit.json",
                 {"audited_at": f"{audit_date or G.today()}T10:00:00",
                  "page_count": 3, "avg_score": 60})
    G.write_json(pdir / "tasks.json", TASKS)
    if verify_date:
        (pdir / "verify").mkdir()
        G.write_json(pdir / "verify" / f"{verify_date}.json",
                     {"verified_at": f"{verify_date}T09:00:00", "audit_avg_score": 60,
                      "changed": 0,
                      "results": [{"id": "T-001", "title": "修标题", "priority": "P0",
                                   "verdict": "通过", "note": "ok"}]})
    for rd in report_dirs:
        rdir = pdir / "reports" / rd
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "report.md").write_text(f"# 报告 {rd}", "utf-8")
    return pdir


class TestRebuild(unittest.TestCase):
    def test_stale_files_removed_on_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d)
            out = Path(d) / "x" / "delivery" / G.today()
            out.mkdir(parents=True)
            (out / "04-验收表.html").write_text("旧", "utf-8")  # 上次条件生成的残留
            (out / "假文件.txt").write_text("旧", "utf-8")
            with mock.patch.object(G, "WORK", Path(d)):
                DL.run("x")
            self.assertFalse((out / "假文件.txt").exists())


class TestUnverified(unittest.TestCase):
    def test_no_verify_marked_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d)
            with mock.patch.object(G, "WORK", Path(d)):
                out = DL.run("x")
            vmd = (out / "04-验收表.md").read_text("utf-8")
            self.assertIn("本期未验收", vmd)
            self.assertIn("尚无验收记录", vmd)
            self.assertIn("本期未验收", (out / "README.md").read_text("utf-8"))

    def test_verify_older_than_audit_marked_unverified(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d, audit_date="2026-07-28", verify_date="2026-07-27")
            with mock.patch.object(G, "WORK", Path(d)):
                out = DL.run("x")
            vmd = (out / "04-验收表.md").read_text("utf-8")
            self.assertIn("本期未验收", vmd)
            self.assertIn("2026-07-27", vmd)
            self.assertNotIn("| 编号 | 任务 |", vmd)  # 不静默复用旧验收结果

    def test_verify_same_day_used(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d, verify_date=G.today())
            with mock.patch.object(G, "WORK", Path(d)):
                out = DL.run("x")
            vmd = (out / "04-验收表.md").read_text("utf-8")
            self.assertIn("| 编号 | 任务 |", vmd)
            self.assertNotIn("本期未验收", vmd)


class TestReportDateConsistency(unittest.TestCase):
    def test_mismatch_triggers_report_rerun(self):
        # 今天有体检但最新报告是昨天的：先补跑报告
        with tempfile.TemporaryDirectory() as d:
            _project(d, report_dirs=["2026-07-27"])

            def fake_run(slug):
                rdir = Path(d) / slug / "reports" / G.today()
                rdir.mkdir(parents=True)
                (rdir / "report.md").write_text("# 今日报告", "utf-8")

            with mock.patch.object(G, "WORK", Path(d)), \
                    mock.patch.object(R, "run", side_effect=fake_run) as m:
                out = DL.run("x")
            m.assert_called_once_with("x")
            self.assertEqual((out / "01-诊断报告.md").read_text("utf-8"), "# 今日报告")
            self.assertNotIn("诊断报告日期", (out / "README.md").read_text("utf-8"))

    def test_mismatch_noted_when_rerun_fails(self):
        with tempfile.TemporaryDirectory() as d:
            _project(d, audit_date="2026-07-28", report_dirs=["2026-07-26"])
            with mock.patch.object(G, "WORK", Path(d)), \
                    mock.patch.object(R, "run", side_effect=RuntimeError("boom")):
                out = DL.run("x")
            readme = (out / "README.md").read_text("utf-8")
            self.assertIn("诊断报告日期 2026-07-26", readme)
            self.assertIn("本期体检日期 2026-07-28", readme)


if __name__ == "__main__":
    unittest.main()
