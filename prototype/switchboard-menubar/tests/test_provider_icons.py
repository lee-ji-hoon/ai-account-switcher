import struct
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ICONS = ROOT / "Resources" / "provider-icons"
SOURCE = ROOT / "Sources" / "main.swift"
RUN_SCRIPT = ROOT / "run.sh"
EXPECTED = {
    "claude.jpg": (512, 512),
    "codex.png": (1024, 1024),
    "grok.jpg": (512, 512),
    "gemini.jpg": (512, 512),
}


def jpeg_dimensions(path):
    data = path.read_bytes()
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    offset = 2
    while offset < len(data):
        if data[offset] != 0xFF:
            offset += 1
            continue
        marker = data[offset + 1]
        offset += 2
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            continue
        length = struct.unpack(">H", data[offset : offset + 2])[0]
        if 0xC0 <= marker <= 0xC3:
            height, width = struct.unpack(">HH", data[offset + 3 : offset + 7])
            return width, height
        offset += length
    raise ValueError("JPEG dimensions not found")


def image_dimensions(path):
    if path.suffix == ".png":
        data = path.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("not a PNG")
        return struct.unpack(">II", data[16:24])
    return jpeg_dimensions(path)


class ProviderIconContractTest(unittest.TestCase):
    def test_all_provider_app_icons_are_original_files_at_expected_size(self):
        for filename, dimensions in EXPECTED.items():
            icon = ICONS / filename
            self.assertTrue(icon.is_file(), icon)
            self.assertEqual(dimensions, image_dimensions(icon))

    def test_icon_sources_record_publisher_bundle_and_non_affiliation(self):
        sources = (ICONS / "SOURCES.md").read_text(encoding="utf-8")
        self.assertIn("Retrieved 2026-08-17", sources)
        self.assertIn("Switchboard is not affiliated with", sources)
        self.assertIn("endorsed by, or sponsored by any provider", sources)
        for expected in (
            "Anthropic PBC",
            "com.anthropic.claude",
            "OpenAI OpCo LLC",
            "com.openai.codex",
            "/Applications/ChatGPT.app/Contents/Resources/icon-codex-dark-color.png",
            "69fb4384e161be8a20dcb94a9ac34aea4fbfaeb67514110a71e7b0732eccb0fc",
            "https://help.openai.com/en/articles/20001276/",
            "X Corp",
            "ai.x.GrokApp",
            "Google LLC",
            "com.google.gemini",
            "https://x.ai/legal/brand-guidelines",
        ):
            self.assertIn(expected, sources)

    def test_bundle_copy_requires_and_copies_each_provider_icon(self):
        script = RUN_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('command rm -rf "$APP_DIR"', script)
        self.assertLess(script.index('command rm -rf "$APP_DIR"'), script.index('mkdir -p "$APP_DIR'))
        self.assertIn("Required provider icon source is missing", script)
        for filename in EXPECTED:
            self.assertIn(filename, script)
            self.assertIn("ProviderIcon-$provider_icon", script)

    def test_provider_mark_uses_bundled_brand_icon_with_symbol_fallback(self):
        source = SOURCE.read_text(encoding="utf-8")
        provider_mark = source.split("struct ProviderMark: View", 1)[1].split(
            "struct UsageRing", 1
        )[0]
        self.assertIn("Bundle.main.url(", provider_mark)
        self.assertIn("forResource: provider.appIconResourceName", provider_mark)
        self.assertIn("provider.appIconResourceExtension", provider_mark)
        self.assertIn("Image(nsImage: brandIcon)", provider_mark)
        self.assertIn("Image(systemName: id.icon)", provider_mark)
        self.assertIn('self == .codex ? "png" : "jpg"', source)
        self.assertIn(".aspectRatio(contentMode: .fit)", provider_mark)
        self.assertNotIn(".aspectRatio(contentMode: .fill)", provider_mark)
        self.assertNotIn(".clipShape", provider_mark)
        self.assertIn("appIconResourceName", source)

    def test_account_layout_keeps_long_identifiers_and_quota_details_readable(self):
        source = SOURCE.read_text(encoding="utf-8")
        account_row = source.split("struct AccountRow: View", 1)[1].split(
            "struct AccountBadge", 1
        )[0]
        quota_chip = source.split("struct QuotaChip: View", 1)[1].split(
            "struct RecommendationBanner", 1
        )[0]
        self.assertIn(".truncationMode(.middle)", account_row)
        self.assertIn(".layoutPriority(2)", account_row)
        self.assertIn(".fixedSize(horizontal: true, vertical: false)", account_row)
        self.assertIn("QuotaChip(window: window)", account_row)
        self.assertIn(".minimumScaleFactor", quota_chip)
        self.assertIn("계정 전환 미지원", source)
        recommendation = source.split("struct RecommendationBanner: View", 1)[1].split(
            "struct UnavailableUsageLine", 1
        )[0]
        self.assertIn(".lineLimit(3)", recommendation)
        self.assertIn(".fixedSize(horizontal: false, vertical: true)", recommendation)
        self.assertIn(".fixedSize(horizontal: true, vertical: false)", recommendation)


if __name__ == "__main__":
    unittest.main()
