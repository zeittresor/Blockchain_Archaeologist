import unittest

from chain_archaeologist.script_parser import data_pushes, op_return_payloads, ordinal_envelopes


class ScriptParserTests(unittest.TestCase):
    def test_op_return(self):
        script = bytes([0x6A, 0x05]) + b"hello"
        self.assertEqual(op_return_payloads(script), [b"hello"])

    def test_pushes(self):
        script = bytes([0x03]) + b"abc" + bytes([0x02]) + b"de"
        self.assertEqual(data_pushes(script), [b"abc", b"de"])

    def test_ordinal_envelope(self):
        mime = b"text/plain"
        body = b"hello"
        script = (
            b"\x00\x63" + bytes([3]) + b"ord" +
            bytes([1]) + b"\x01" + bytes([len(mime)]) + mime +
            b"\x00" + bytes([len(body)]) + body + b"\x68"
        )
        envs = ordinal_envelopes(script)
        self.assertEqual(len(envs), 1)
        self.assertEqual(envs[0].content_type, "text/plain")
        self.assertEqual(envs[0].body, b"hello")


if __name__ == "__main__":
    unittest.main()
