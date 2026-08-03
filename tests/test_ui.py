import re
import unittest
from pathlib import Path

UI = Path(__file__).parent.parent / "scripts" / "ui.html"


class DocumentLangCase(unittest.TestCase):
    """回归：界面语言切换必须同步 <html lang>（WCAG 3.1.1，issue #1）。"""

    def setUp(self):
        self.html = UI.read_text("utf-8")

    def test_default_lang_is_zh_cn(self):
        self.assertIn('<html lang="zh-CN">', self.html)

    def test_ulang_updates_document_lang(self):
        m = re.search(
            r"document\.documentElement\.lang\s*=\s*(\{[^}]*\})\[ULANG\]", self.html
        )
        self.assertIsNotNone(m, "ULANG 未同步到 document.documentElement.lang")
        mapping = m.group(1)
        self.assertIn("zh:'zh-CN'", mapping)
        self.assertIn("'zh-tw':'zh-TW'", mapping)
        self.assertIn("en:'en'", mapping)
        self.assertIn("ja:'ja'", mapping)

    def test_traditional_chinese_locale_is_available(self):
        self.assertIn("['zh-tw','繁']", self.html)
        self.assertIn("生成式引擎最佳化平台", self.html)
        self.assertIn("UI_D['zh-tw']", self.html)

    def test_traditional_character_map_is_balanced(self):
        source = re.search(r"const ZHTW_FROM='([^']+)'", self.html)
        target = re.search(r"const ZHTW_TO='([^']+)'", self.html)
        self.assertIsNotNone(source)
        self.assertIsNotNone(target)
        self.assertEqual(len(source.group(1)), len(target.group(1)))


if __name__ == "__main__":
    unittest.main()
