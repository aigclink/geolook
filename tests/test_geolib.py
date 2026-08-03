import json, tempfile, unittest
from pathlib import Path
import sys; sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import geolib as G

class TestJsonIO(unittest.TestCase):
    def test_write_json_atomic(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            G.write_json(p, {"a": 1})
            self.assertEqual(G.read_json(p), {"a": 1})
            self.assertFalse(list(Path(d).glob("*.tmp")))

    def test_read_json_corrupt_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.json"
            p.write_text("{broken", "utf-8")
            self.assertEqual(G.read_json(p, default={}), {})

    def test_project_dir_rejects_traversal(self):
        for bad in ("../x", "/etc", "a/b", ".."):
            with self.assertRaises(SystemExit):
                G.project_dir(bad)

    def test_project_dir_accepts_valid_slug(self):
        self.assertEqual(G.project_dir("aigclink"), G.WORK / "aigclink")

    def test_read_json_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.json"
            self.assertEqual(G.read_json(p, default={"x": 1}), {"x": 1})
            self.assertIsNone(G.read_json(p))

    def test_main_text_single_article_stays_focused(self):
        soup = G.parse_html(
            "<main><nav>menu</nav><article>the post body</article></main>")
        self.assertEqual(G.main_text(soup), "the post body")

    def test_main_text_multiple_articles_takes_whole_main(self):
        soup = G.parse_html(
            "<main><article>intro section</article>"
            "<article>steps: 1 2 3</article>"
            "<article>faq answers</article></main>")
        text = G.main_text(soup)
        for piece in ("intro section", "steps: 1 2 3", "faq answers"):
            self.assertIn(piece, text)

    def test_jsonl_roundtrip_with_unicode_line_separators(self):
        """正文含 U+2028/U+2029/U+0085 时 JSONL 必须仍能读回。

        json.dumps 不转义这些字符，而 str.splitlines() 会在它们处断行，
        导致一条记录被劈成两半。真实触发场景：抓取的网页正文里带 U+2028。
        """
        rows = [
            {"url": "https://a.example/1", "text": "line one\u2028line two"},
            {"url": "https://a.example/2", "text": "para\u2029break"},
            {"url": "https://a.example/3", "text": "next\u0085line"},
            {"url": "https://a.example/4", "text": "vert\u000btab and form\u000cfeed"},
            {"url": "https://a.example/5", "text": "plain"},
        ]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "pages.jsonl"
            G.write_jsonl(p, rows)
            # 前提确认：这些字符确实原样落盘了，否则本测试没有鉴别力
            self.assertIn("\u2028", p.read_text("utf-8"))
            self.assertEqual(G.read_jsonl(p), rows)

    def test_project_lock_enter_exit(self):
        with tempfile.TemporaryDirectory() as d:
            slug = "locktest"
            orig_work = G.WORK
            G.WORK = Path(d)
            try:
                with G.project_lock(slug):
                    self.assertTrue((Path(d) / slug / ".lock").exists())
                self.assertTrue((Path(d) / slug / ".lock").exists())
            finally:
                G.WORK = orig_work

if __name__ == "__main__":
    unittest.main()
