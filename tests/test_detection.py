import unittest

from chain_archaeologist.detection import detect_payload, shannon_entropy


class DetectionTests(unittest.TestCase):
    def test_png(self):
        result = detect_payload(b"\x89PNG\r\n\x1a\n" + b"x" * 32)
        self.assertEqual(result.extension, ".png")
        self.assertGreaterEqual(result.confidence, 0.95)
        self.assertEqual(result.magic_offset, 0)

    def test_json_preview(self):
        result = detect_payload(b'{"hello":"world"}')
        self.assertEqual(result.mime, "application/json")
        self.assertIsNotNone(result.preview_text)

    def test_unknown(self):
        result = detect_payload(bytes(range(1, 32)))
        self.assertEqual(result.extension, ".bin")

    def test_entropy(self):
        self.assertEqual(shannon_entropy(b"aaaa"), 0.0)
        self.assertGreater(shannon_entropy(bytes(range(256))), 7.9)


if __name__ == "__main__":
    unittest.main()
