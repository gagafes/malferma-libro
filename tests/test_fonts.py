"""Check real font fallback through Pango without claiming GTK rendering."""

import os
import tempfile
import unittest
from unittest.mock import patch

from malferma_libro.appearance import FONT_FAMILIES, register_fonts


class FontCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cache = tempfile.TemporaryDirectory(prefix="malferma-font-cache-")
        cls.addClassCleanup(cache.cleanup)
        environment = patch.dict(os.environ, {"XDG_CACHE_HOME": cache.name})
        environment.start()
        cls.addClassCleanup(environment.stop)
        try:
            import gi
            gi.require_version("Pango", "1.0")
            gi.require_version("PangoCairo", "1.0")
            from gi.repository import Pango, PangoCairo
        except (ImportError, ValueError) as error:
            raise unittest.SkipTest(f"Pango/Fontconfig unavailable: {error}") from error
        if not register_fonts():
            raise unittest.SkipTest("Bundled fonts could not be registered through Fontconfig")
        cls.Pango = Pango
        cls.font_map = PangoCairo.FontMap.get_default()

    def test_reader_font_choices_cover_the_supported_scripts(self):
        samples = (
            "Леся Українка — Її вірші; Қазақ тілі: Ә Ғ Қ Ң Ө Ұ Ү Һ І",
            "Esperanto: ĉ ĝ ĥ ĵ ŝ ŭ; Français: œ ç; Deutsch: ä ö ü ß; Łódź",
            "العربية فارسی اردو — پ چ ژ گ",
            "עברית ייִדיש — אָ בּ שׁ",
            "አማርኛ መጽሐፍ",
        )
        for family, (_, css) in FONT_FAMILIES.items():
            if family == "system":
                continue
            description = self.Pango.FontDescription()
            description.set_family(css.replace('"', ''))
            description.set_size(20 * self.Pango.SCALE)
            for sample in samples:
                with self.subTest(font=family, text=sample):
                    layout = self.Pango.Layout.new(self.font_map.create_context())
                    layout.set_font_description(description)
                    layout.set_text(sample, -1)
                    self.assertEqual(layout.get_unknown_glyphs_count(), 0)


if __name__ == "__main__":
    unittest.main()
