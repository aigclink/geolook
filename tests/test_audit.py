import json
import tempfile
import unittest
from pathlib import Path
import sys; sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import audit as A
import geolib as G
import tasks as T


def make_page(url="https://example.com/", text="", wc=None, **kw):
    page = {
        "url": url, "title": "", "status": 200, "meta_robots": "",
        "canonical": url, "h1": ["t"], "h2": ["a"] * 6,
        "para_count": 10, "li_count": 5, "table_count": 0,
        "jsonld_types": ["WebSite"], "jsonld_raw": [],
        "external_links": 5, "text": text,
        "word_count": wc if wc is not None else G.word_count(text),
    }
    page.update(kw)
    return page


SPA_TEXT = "加载中"  # 空壳：远低于 120 词


class TestIssueCodes(unittest.TestCase):
    def test_spa_shell_has_code(self):
        r = A.score_page(make_page(text=SPA_TEXT), [])
        self.assertIn("SPA_SHELL", r["issue_codes"])
        self.assertEqual(len(r["issue_codes"]), len(r["issues"]))

    def test_functional_page_exempt(self):
        r = A.score_page(make_page(url="https://example.com/login", text=SPA_TEXT), [])
        self.assertNotIn("SPA_SHELL", r["issue_codes"])
        self.assertIn("LOW_CONTENT_PAGE", r["issue_codes"])
        self.assertFalse(any(i.startswith("P0 静态 HTML") for i in r["issues"]))

    def test_functional_page_case_insensitive(self):
        r = A.score_page(make_page(url="https://example.com/Auth/SignIn", text=SPA_TEXT), [])
        self.assertIn("LOW_CONTENT_PAGE", r["issue_codes"])
        self.assertNotIn("SPA_SHELL", r["issue_codes"])

    def test_normal_low_page_still_spa(self):
        r = A.score_page(make_page(url="https://example.com/products", text=SPA_TEXT), [])
        self.assertIn("SPA_SHELL", r["issue_codes"])


class TestHowto(unittest.TestCase):
    def test_ruhe_without_steps_not_howto(self):
        text = "如何选择合适的方案？这是很多用户关心的问题。" * 10
        r = A.score_page(make_page(text=text, li_count=0), [])
        self.assertFalse(r["blocks"]["操作步骤"])

    def test_numbered_steps_is_howto(self):
        text = "第一步：注册账号。第二步：填写资料。第三步：提交审核。" * 5
        r = A.score_page(make_page(text=text, li_count=0), [])
        self.assertTrue(r["blocks"]["操作步骤"])

    def test_ruhe_with_list_is_howto(self):
        text = "怎么配置环境？请按下面的要点操作。" * 10
        r = A.score_page(make_page(text=text, li_count=6), [])
        self.assertTrue(r["blocks"]["操作步骤"])


class TestJapaneseBlocks(unittest.TestCase):
    def test_ja_definition_detected(self):
        text = "GeoLookとは、生成エンジン最適化のための診断ツールです。" * 5
        r = A.score_page(make_page(text=text), [])
        self.assertTrue(r["blocks"]["定义"])

    def test_ja_howto_detected(self):
        text = "導入の手順：まずアカウントを作成し、次にサイトを登録します。" * 5
        r = A.score_page(make_page(text=text), [])
        self.assertTrue(r["blocks"]["操作步骤"])

    def test_ja_faq_detected(self):
        text = "よくある質問：料金はいくらですか。プランによって異なります。" * 5
        r = A.score_page(make_page(text=text), [])
        self.assertTrue(r["blocks"]["FAQ"])

    def test_ja_numbers_detected(self):
        text = "導入企業は 300社、月間 5億回 の処理、平均 24時間 で稼働開始。" * 3
        r = A.score_page(make_page(text=text), [])
        self.assertTrue(r["blocks"]["数字事实"])

    def test_contact_page_is_functional(self):
        r = A.score_page(make_page(url="https://example.com/contact", text=SPA_TEXT), [])
        self.assertIn("LOW_CONTENT_PAGE", r["issue_codes"])
        self.assertNotIn("SPA_SHELL", r["issue_codes"])


class TestLanguage(unittest.TestCase):
    def test_japanese_detected(self):
        text = "これはテストページです。私たちは最高のサービスを提供します。詳細についてはお問い合わせください。" * 3
        self.assertEqual(G.page_language(text), "ja")

    def test_chinese_not_japanese(self):
        text = "这是一个中文页面，用来测试语言检测是否会把纯中文误判成日文。" * 3
        self.assertEqual(G.page_language(text), "zh")

    def test_english_still_english(self):
        text = "This is an English page about our product and services for testing." * 3
        self.assertEqual(G.page_language(text), "en")


class TestNormalizeUrl(unittest.TestCase):
    def test_strips_tracking_params(self):
        u = G.normalize_url("https://example.com/", "/p?utm_source=x&fbclid=y&id=42&gclid=z")
        self.assertEqual(u, "https://example.com/p?id=42")

    def test_strips_ref_spm(self):
        u = G.normalize_url("https://example.com/", "https://example.com/a?ref=nav&spm=1.2.3&lang=zh")
        self.assertEqual(u, "https://example.com/a?lang=zh")

    def test_no_query_unchanged(self):
        u = G.normalize_url("https://example.com/", "/about#team")
        self.assertEqual(u, "https://example.com/about")


class TestKeywords(unittest.TestCase):
    def test_brand_terms_excluded(self):
        cfg = {"brand": {"name": "甲工智能", "aliases": ["甲工"], "products": ["甲工云"]},
               "questions": [{"text": "智能体平台怎么选？有哪些好用的替代品？"}]}
        kws = A.keywords_from_config(cfg)
        self.assertNotIn("甲工智能", kws)
        self.assertNotIn("甲工", kws)
        self.assertNotIn("甲工云", kws)
        self.assertIn("智能体平台怎么选", kws)
        self.assertIn("有哪些好用的替代品", kws)


class TestBaselineCount(unittest.TestCase):
    def test_block_task_baseline_not_truncated(self):
        pages = []
        for i in range(35):
            pages.append({"url": f"https://example.com/p{i}", "score": 50,
                          "word_count": 500, "jsonld_types": ["Article"],
                          "issue_codes": [], "issues": [],
                          "blocks": {"定义": False, "数字事实": False, "对比": False,
                                     "操作步骤": False, "FAQ": False}})
        audit = {"site": {"has_sitemap": True, "has_llms_txt": True},
                 "pages": pages, "avg_score": 50,
                 "block_gap": [{"block": "定义", "missing_pages": 35, "total": 35}]}
        cfg = {"market": "cn", "brand": {"name": "X", "site": "https://example.com"}}
        out = T.from_audit(audit, cfg, iter(f"T-{i:03d}" for i in range(1, 99)))
        blk = [t for t in out if t["acceptance"].get("check") == "pages.block:定义"]
        self.assertEqual(len(blk), 1)
        self.assertEqual(len(blk[0]["affected"]), 30)
        self.assertEqual(blk[0]["baseline_count"], 35)


class TestAvgScore(unittest.TestCase):
    def test_zero_score_200_pages_counted(self):
        pages = [make_page(url="https://example.com/a", text=SPA_TEXT),
                 make_page(url="https://example.com/b", text=SPA_TEXT, status=404)]
        results = [A.score_page(p, []) for p in pages]
        ok = [r for r, p in zip(results, pages) if (p.get("status") or 0) == 200]
        avg = round(sum(r["score"] for r in ok) / max(len(ok), 1), 1)
        self.assertEqual(len(ok), 1)
        self.assertEqual(avg, results[0]["score"])


class TestJsonldDate(unittest.TestCase):
    def test_date_modified_in_jsonld_counts(self):
        raw = [{"@type": "Article", "dateModified": "2026-01-01"}]
        r = A.score_page(make_page(text=SPA_TEXT * 1, jsonld_raw=raw), [])
        self.assertNotIn("NO_DATE", r["issue_codes"])

    def test_no_date_anywhere(self):
        r = A.score_page(make_page(text=SPA_TEXT, jsonld_raw=[{"@type": "Article"}]), [])
        self.assertIn("NO_DATE", r["issue_codes"])


class TestLanguageRecompute(unittest.TestCase):
    """evidence 是旧口径抓的（language 存成 zh），audit 必须从正文重算语言。"""

    def test_stale_language_field_recomputed(self):
        ja_text = "これはテストページです。私たちは最高のサービスを提供します。詳細についてはお問い合わせください。" * 3
        zh_text = "这是一个中文页面，介绍我们的产品和服务，帮助客户解决问题。" * 5
        with tempfile.TemporaryDirectory() as d:
            orig_work = G.WORK
            G.WORK = Path(d)
            try:
                pdir = G.project_dir("langtest")
                (pdir / "evidence").mkdir(parents=True)
                (pdir / "geo.json").write_text(json.dumps(
                    {"brand": {"name": "T", "site": "https://example.com"}, "market": "cn"},
                    ensure_ascii=False), "utf-8")
                pages = [
                    make_page(url="https://example.com/ja/", text=ja_text, language="zh", wc=200),
                    make_page(url="https://example.com/zh/", text=zh_text, language="zh", wc=200),
                ]
                G.write_jsonl(pdir / "evidence" / "pages.jsonl", pages)
                G.write_json(pdir / "evidence" / "site.json",
                             {"has_sitemap": True, "has_llms_txt": True})
                out = A.run("langtest")
            finally:
                G.WORK = orig_work
        lc = out["language_coverage"]
        self.assertEqual(lc["ja_pages"], 1)
        self.assertEqual(lc["zh_pages"], 1)


if __name__ == "__main__":
    unittest.main()
