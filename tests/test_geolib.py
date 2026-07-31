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
