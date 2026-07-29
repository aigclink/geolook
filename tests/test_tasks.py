import itertools
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G
import tasks as T
import verify as V
import deliverables as D


def _plat(market="cn", mention=0.2, cite=0.5):
    """mention/cite 传 None 表示该平台只采了点名题（未测）。"""
    return {"market": market, "label": "X", "samples": 3 if mention is not None else 0,
            "mention_rate": mention, "top1_rate": mention, "top3_rate": mention,
            "avg_rank": 2.0, "own_domain_cite_rate": cite,
            "competitor_mentions": {}, "top_cited_domains": {},
            "probe": {"samples": 2, "recognized_rate": 1.0, "own_domain_cite_rate": 0.5}}


def _metrics(plats):
    return {"slug": "x", "date": "2026-07-28", "question_count": 5,
            "sample_count": 10, "platforms": plats}


CFG = {"brand": {"name": "X", "site": "https://x.com"},
       "market": "cn", "targets": {"mention_rate": 0.3}}


def _seq():
    return map(lambda i: f"T-{i:03d}", itertools.count(1))


class TestFromMetricsNone(unittest.TestCase):
    def test_probe_only_platform_skipped_in_avg(self):
        # 一个已测平台 0.6（≥ 目标不下工单）+ 一个全点名平台 None：不崩且 None 被跳过
        m = _metrics({"deepseek": _plat(mention=0.6), "kimi": _plat(mention=None, cite=None)})
        out = T.from_metrics(m, CFG, _seq())
        self.assertFalse(any("提及率" in t["title"] for t in out))

    def test_all_none_market_no_conclusion_task(self):
        # 整个市场全是点名样本：可见性「未测」，不能按 0% 误下「未达标」工单
        m = _metrics({"deepseek": _plat(mention=None, cite=None)})
        out = T.from_metrics(m, CFG, _seq())
        self.assertFalse(any("提及率" in t["title"] for t in out))
        self.assertFalse(any("检索结果" in t["title"] for t in out))

    def test_low_measured_avg_still_creates_task(self):
        m = _metrics({"deepseek": _plat(mention=0.0, cite=0.0), "kimi": _plat(mention=None, cite=None)})
        out = T.from_metrics(m, CFG, _seq())
        self.assertTrue(any("提及率" in t["title"] for t in out))
        self.assertTrue(any("检索结果" in t["title"] for t in out))


class TestMarketAvg(unittest.TestCase):
    def test_none_values_skipped(self):
        m = _metrics({"a": _plat(mention=0.6), "b": _plat(mention=None, cite=None)})
        self.assertAlmostEqual(V._market_avg(m, "cn", "mention_rate"), 0.6)

    def test_all_none_returns_none(self):
        m = _metrics({"a": _plat(mention=None, cite=None)})
        self.assertIsNone(V._market_avg(m, "cn", "mention_rate"))
        self.assertIsNone(V._market_avg(m, "cn", "own_domain_cite_rate"))

    def test_check_all_none_market_not_failed(self):
        m = _metrics({"a": _plat(mention=None, cite=None)})
        task = {"acceptance": {"type": "auto", "check": "metrics.mention_rate_gte:cn:0.3"}}
        ok, why = V.check(task, {}, m)
        self.assertIsNone(ok)  # 无数据 → 无法判定，而不是 False「未达标」


class TestDeliverablesNone(unittest.TestCase):
    def test_optimization_plan_with_probe_only_metrics(self):
        with tempfile.TemporaryDirectory() as d:
            slug = "probetest"
            pdir = Path(d) / slug
            (pdir / "metrics").mkdir(parents=True)
            (pdir / "geo.json").write_text(json.dumps(
                {"brand": {"name": "X", "site": "https://x.com"},
                 "market": "cn", "targets": {"mention_rate": 0.3}}, ensure_ascii=False), "utf-8")
            G.write_json(pdir / "metrics" / "2026-07-28.json",
                         _metrics({"deepseek": _plat(mention=None, cite=None)}))
            with mock.patch.object(G, "WORK", Path(d)):
                md = D.optimization_plan(slug)
        self.assertIn("未测", md)


if __name__ == "__main__":
    unittest.main()
