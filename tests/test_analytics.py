import json
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import geolib as G
import analytics as A

CFG = {
    "brand": {"name": "Acme", "site": "https://www.acme.com", "aliases": []},
    "market": "both",
    "competitors": [
        {"name": "国内对手", "market": "cn", "aliases": []},
        {"name": "GlobalRival", "market": "global", "aliases": []},
        {"name": "通用对手", "aliases": []},
    ],
    "questions": [
        {"id": "q1", "text": "有什么好用的方案工具？", "group": "推荐", "market": "cn"},
        {"id": "q2", "text": "Acme 是什么？", "group": "品牌验证", "market": "cn"},
        {"id": "q3", "text": "Best proposal tools?", "group": "推荐", "market": "global"},
    ],
}


def row(qid="q1", question="有什么好用的方案工具？", platform="p1", market="cn",
        probe=False, mentioned=False, cites=None, comps=None, rank=None,
        own_cited=False, ok=True):
    cites = cites or []
    return {
        "ok": ok, "platform": platform, "market": market, "question_id": qid,
        "question": question, "date": "2026-07-27", "brand_in_question": probe,
        "search_enabled": True, "answer": "some answer text",
        "analysis": {
            "brand_mentioned": mentioned, "brand_rank": rank,
            "cited_domains": cites, "own_domain_cited": own_cited,
            "competitors_mentioned": comps or [],
        },
    }


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old_work = G.WORK
        G.WORK = Path(self._tmp.name)

    def tearDown(self):
        G.WORK = self._old_work
        self._tmp.cleanup()

    def make_project(self, cfg=None, samples=None):
        pdir = G.WORK / "demo"
        (pdir / "samples").mkdir(parents=True, exist_ok=True)
        (pdir / "geo.json").write_text(
            json.dumps(cfg or CFG, ensure_ascii=False), "utf-8")
        for name, rows in (samples or {}).items():
            G.write_jsonl(pdir / "samples" / name, rows)
        return pdir


class TestHealthCite(Base):
    def test_cite_sub_excludes_probe(self):
        self.make_project()
        rows = [
            row(probe=False, cites=["other.com"]),
            row(probe=True, qid="q2", question="Acme 是什么？", cites=["acme.com"]),
        ]
        h = A.health("demo", None, [], rows)
        self.assertEqual(h["subs"]["cite"], 0.0)


class TestVerdict(Base):
    def test_single_platform_no_best_claim(self):
        self.make_project()
        rows = [row(platform="only", mentioned=True) for _ in range(3)]
        engs = A.engines("demo", rows, None)
        self.assertEqual(len(engs), 1)
        self.assertNotIn("最好", engs[0]["verdict"])

    def test_all_zero_no_best_claim(self):
        self.make_project()
        rows = [row(platform="a"), row(platform="b")]
        verdicts = [e["verdict"] for e in A.engines("demo", rows, None)]
        self.assertFalse(any("最好" in v for v in verdicts))

    def test_all_equal_no_best_claim(self):
        self.make_project()
        rows = [row(platform="a", mentioned=True), row(platform="b", mentioned=True)]
        verdicts = [e["verdict"] for e in A.engines("demo", rows, None)]
        self.assertFalse(any("最好" in v for v in verdicts))

    def test_best_only_when_strictly_ahead(self):
        self.make_project()
        rows = ([row(platform="a", mentioned=True) for _ in range(3)]
                + [row(platform="b", mentioned=True)] + [row(platform="b") for _ in range(2)])
        engs = {e["platform"]: e for e in A.engines("demo", rows, None)}
        self.assertIn("最好", engs["a"]["verdict"])
        self.assertNotIn("最好", engs["b"]["verdict"])

    def test_peers_all_none_no_best_claim(self):
        self.make_project()
        rows = [row(platform="a", mentioned=True),
                row(platform="b", probe=True, qid="q2", question="Acme 是什么？", mentioned=True)]
        engs = {e["platform"]: e for e in A.engines("demo", rows, None)}
        self.assertNotIn("最好", engs["a"]["verdict"])


class TestEnginesCiteShare(Base):
    def test_cite_share_uses_unprompted_rows(self):
        self.make_project()
        rows = [
            row(probe=False, cites=["other.com"]),
            row(probe=True, qid="q2", question="Acme 是什么？", cites=["acme.com"]),
        ]
        engs = A.engines("demo", rows, None)
        self.assertEqual(engs[0]["cite_share"], 0.0)
        self.assertEqual(engs[0]["cite_counts"], [0, 1])


class TestCompetitors(Base):
    def test_split_by_market(self):
        self.make_project()
        rows = [
            row(market="cn", comps=["国内对手"]),
            row(market="cn"),
            row(qid="q3", question="Best proposal tools?", platform="p2",
                market="global", comps=["GlobalRival", "国内对手"]),
        ]
        c = A.competitors("demo", rows)
        cn = {x["name"]: x for x in c["tables"]["cn"]}
        gl = {x["name"]: x for x in c["tables"]["global"]}
        self.assertIn("国内对手", cn)
        self.assertNotIn("国内对手", gl)
        self.assertIn("GlobalRival", gl)
        self.assertNotIn("GlobalRival", cn)
        self.assertIn("通用对手", cn)
        self.assertIn("通用对手", gl)
        self.assertEqual(cn["国内对手"]["presence"], 0.5)
        self.assertEqual(gl["GlobalRival"]["presence"], 1.0)
        self.assertEqual(c["sample_ns"], {"cn": 2, "global": 1})


class TestProbeQuestions(Base):
    def test_probe_not_in_gap_pool_and_has_own_rate(self):
        self.make_project()
        rows = [row(probe=True, qid="q2", question="Acme 是什么？", mentioned=True)]
        qs = A.questions("demo", rows, None)
        probe = [q for q in qs if q["brand_probe"]]
        self.assertEqual([q["id"] for q in probe], ["q2"])
        self.assertEqual(probe[0]["mention"], 1.0)
        self.assertEqual(probe[0]["samples"], 1)
        self.assertEqual(qs[-1]["id"], "q2")
        self.assertTrue(all(not q["brand_probe"] for q in qs[:-1]))

    def test_probe_flag_without_samples(self):
        self.make_project()
        qs = A.questions("demo", [], None)
        self.assertTrue(next(q for q in qs if q["id"] == "q2")["brand_probe"])


class TestTrend(Base):
    def test_probe_only_day_is_none(self):
        self.make_project(samples={
            "2026-07-27.jsonl": [row(probe=True, qid="q2", question="Acme 是什么？",
                                     mentioned=True)],
        })
        tr = A.trend("demo")
        self.assertEqual(len(tr), 1)
        self.assertIsNone(tr[0]["mention"])
        self.assertIsNone(tr[0]["cite"])

    def test_mixed_day_measured(self):
        self.make_project(samples={
            "2026-07-27.jsonl": [row(mentioned=True), row()],
        })
        tr = A.trend("demo")
        self.assertEqual(tr[0]["mention"], 0.5)


class TestQuestionDelta(Base):
    def test_untested_sorted_last(self):
        before = [row(qid="q1", mentioned=True),
                  row(qid="q3", question="Best proposal tools?",
                      platform="p2", market="global", mentioned=True)]
        after = [row(qid="q1")]
        self.make_project(samples={
            "2026-07-26.jsonl": before,
            "2026-07-27.jsonl": after,
        })
        d = A.question_delta("demo")
        self.assertEqual(d[0]["qid"], "q1")
        self.assertEqual(d[-1]["qid"], "q3")
        self.assertIsNone(d[-1]["after"])
        self.assertEqual(d[-1].get("note"), "本期未测")


if __name__ == "__main__":
    unittest.main()
