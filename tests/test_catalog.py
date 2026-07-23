import tempfile
import unittest
from pathlib import Path

from chain_archaeologist.catalog import CandidateRecord, Catalog


class CatalogTests(unittest.TestCase):
    def test_insert_and_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "catalog.sqlite3"
            catalog = Catalog(db)
            record = CandidateRecord(
                chain_id="bitcoin", block_height=1, block_hash="00", block_time=1,
                txid="11", tx_index=0, location="vout[0]", embedding_method="OP_RETURN",
                item_index=0, payload_size=5, sha256="aa", entropy=1.0,
                detected_type="UTF-8 text", extension=".txt", mime="text/plain",
                confidence=0.98, magic_offset=0, preview_text="hello", payload=b"hello",
                metadata={"test": True},
            )
            self.assertEqual(catalog.add_many([record]), 1)
            self.assertEqual(catalog.add_many([record]), 0)
            rows = catalog.query("bitcoin")
            self.assertEqual(len(rows), 1)
            self.assertEqual(bytes(rows[0]["payload"]), b"hello")
            catalog.close()


if __name__ == "__main__":
    unittest.main()
