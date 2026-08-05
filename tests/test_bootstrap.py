import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import bootstrap as B
import generate as GEN
import geolib as G
import sample as S


class WorkDirCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = G.WORK
        G.WORK = Path(self._tmp.name)
        self.slug = "boottest"
        self.pdir = G.project_dir(self.slug)
        (self.pdir / "evidence").mkdir(parents=True)

    def tearDown(self):
        G.WORK = self._orig
        self._tmp.cleanup()

    def write_config(self, cfg):
        self.pdir.mkdir(parents=True, exist_ok=True)
        (self.pdir / "geo.json").write_text(json.dumps(cfg, ensure_ascii=False), "utf-8")


BASE_CFG = {
    "brand": {"name": "测试品牌", "aliases": [], "site": "https://t.example.com"},
    "competitors": [
        {"name": "竞品A", "aliases": [], "market": "cn", "confirmed": False},
        {"name": "竞品B", "aliases": [], "market": "cn", "confirmed": False},
        {"name": "老牌竞品", "aliases": [], "market": "cn"},  # 旧数据无字段，视为已确认
    ],
    "market": "cn",
    "questions": [{"id": "q001", "group": "推荐", "market": "cn", "text": "有什么好用的工具？"}],
}


class TestHomepageFirst(WorkDirCase):
    def test_root_is_first_page_not_highest_scored(self):
        home = "https://t.example.com/"
        deep = "https://t.example.com/blog/hot-article"
        G.write_jsonl(self.pdir / "evidence" / "pages.jsonl", [
            {"url": home, "title": "首页", "text": "首页正文 " * 50, "word_count": 100},
            {"url": deep, "title": "高分页", "text": "高分页正文 " * 50, "word_count": 100},
        ])
        G.write_json(self.pdir / "audit.json", {"pages": [
            {"url": home, "score": 1},
            {"url": deep, "score": 99},
        ]})
        digest = B._site_digest(self.slug)
        blocks = [b for b in digest.split("## 页面：") if b.strip()]
        self.assertTrue(blocks, "digest 不应为空")
        self.assertIn(home, blocks[0], "摘要首块必须是首页（pages.jsonl 第一条），而不是高分页")
        self.assertNotIn(deep, blocks[0])

    def test_spa_metadata_and_jsonld_are_used_when_body_is_empty(self):
        home = "https://t.example.com/"
        G.write_jsonl(self.pdir / "evidence" / "pages.jsonl", [{
            "url": home,
            "title": "测试品牌 - 全球服务",
            "meta_description": "提供全球数字服务。",
            "text": "",
            "word_count": 0,
            "jsonld_raw": [{"@type": "Organization", "name": "测试品牌"}],
        }])
        digest = B._site_digest(self.slug)
        self.assertIn("提供全球数字服务。", digest)
        self.assertIn("测试品牌", digest)
        self.assertIn("Organization", digest)


class TestCompetitorConfirmation(WorkDirCase):
    def _manual_file(self, answer):
        f = Path(self._tmp.name) / "manual.md"
        f.write_text(
            "# 采样表\n\n## platform: deepseek\n> 国内\n\n"
            f"### q001 · 有什么好用的工具？\n\n```answer\n{answer}\n```\n",
            "utf-8")
        return str(f)

    def test_mentioned_competitor_confirmed_after_import(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        S.sample_import(self.slug, self._manual_file("我推荐竞品A，它挺好用的。"))
        cfg = G.load_config(self.slug)
        by_name = {c["name"]: c for c in cfg["competitors"]}
        self.assertTrue(by_name["竞品A"].get("confirmed"), "被采样提到的竞品应转正")
        self.assertFalse(by_name["竞品B"].get("confirmed"), "未被提到的竞品保持未确认")

    def test_no_save_when_nothing_changes(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        S.sample_import(self.slug, self._manual_file("我推荐竞品A。"))
        bak = self.pdir / ".geo.bak"
        n1 = len(list(bak.glob("geo-*.json"))) if bak.exists() else 0
        self.assertEqual(n1, 1, "首次转正应写一次配置（产生一个备份）")
        S.sample_import(self.slug, self._manual_file("我推荐竞品A。"))
        n2 = len(list(bak.glob("geo-*.json")))
        self.assertEqual(n2, 1, "值没有变化时不应再写 geo.json")

    def test_unconfirmed_marked_in_facts_md(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        md = B.render_facts(self.slug, {"name": "测试品牌"})
        self.assertIn("未经采样确认", md)
        unconfirmed_line = next(l for l in md.splitlines() if "竞品A" in l)
        self.assertIn("未经采样确认", unconfirmed_line)
        confirmed_line = next(l for l in md.splitlines() if "老牌竞品" in l)
        self.assertNotIn("未经采样确认", confirmed_line)


class TestDraftPromptCompetitors(WorkDirCase):
    def test_unconfirmed_competitors_excluded_from_prompt(self):
        self.write_config(json.loads(json.dumps(BASE_CFG, ensure_ascii=False)))
        outline = {
            "market": "cn", "target_question": "有什么好用的工具？", "type": "对比",
            "facts_to_use": [], "sections": ["开头", "对比"],
            "requirements": {"min_words": 800, "min_h2": 3},
        }
        captured = {}

        def fake_ask(plat, prompt, timeout=300):
            captured["prompt"] = prompt
            return {"ok": True, "answer": "# 初稿"}

        with mock.patch.object(S, "available", return_value=True), \
             mock.patch.object(S, "ask", side_effect=fake_ask):
            GEN.draft(self.slug, outline, provider="deepseek")
        prompt = captured.get("prompt", "")
        self.assertNotIn("竞品A", prompt, "confirmed:false 的竞品不得进初稿 prompt")
        self.assertNotIn("竞品B", prompt)
        self.assertIn("老牌竞品", prompt, "无 confirmed 字段的旧数据视为已确认")


if __name__ == "__main__":
    unittest.main()
