"""Публичные тесты. Часть из них на исходной версии приложения падает — это нормально."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import process_event


GOOD = {
    "source": "telegram",
    "external_id": "event-100",
    "customer": "Учебный клиент",
    "message": "Нужна доставка в Казань",
}


class LeadProcessorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "leads.sqlite3")

    def tearDown(self):
        self.tmp.cleanup()

    def count(self, table):
        with sqlite3.connect(self.db_path) as conn:
            exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] if exists else 0

    def test_new_lead_creates_one_notification(self):
        response = process_event(dict(GOOD), self.db_path)
        self.assertEqual(response["status"], "created")
        self.assertIsInstance(response["id"], int)
        self.assertEqual(self.count("leads"), 1)
        self.assertEqual(self.count("notifications"), 1)

    def test_retry_is_duplicate_without_new_notification(self):
        first = process_event(dict(GOOD), self.db_path)
        second = process_event(dict(GOOD), self.db_path)
        self.assertEqual(second, {"status": "duplicate", "id": first["id"]})
        self.assertEqual(self.count("leads"), 1)
        self.assertEqual(self.count("notifications"), 1)

    def test_same_external_id_from_different_source_is_new(self):
        first = process_event(dict(GOOD), self.db_path)
        second = process_event({**GOOD, "source": "max"}, self.db_path)
        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "created")
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.count("leads"), 2)
        self.assertEqual(self.count("notifications"), 2)

    def test_missing_customer_is_invalid_and_not_saved(self):
        result = process_event({**GOOD, "customer": "   "}, self.db_path)
        self.assertEqual(result["status"], "invalid")
        self.assertTrue(result.get("reason"))
        self.assertEqual(self.count("leads"), 0)
        self.assertEqual(self.count("notifications"), 0)

    def test_whitespace_is_trimmed_before_comparison(self):
        first = process_event({**GOOD, "source": " telegram ", "external_id": " event-100 "}, self.db_path)
        second = process_event(dict(GOOD), self.db_path)
        self.assertEqual(first["status"], "created")
        self.assertEqual(second, {"status": "duplicate", "id": first["id"]})
        self.assertEqual(self.count("leads"), 1)

    def test_first_event_data_is_preserved_on_retry(self):
        first = process_event(dict(GOOD), self.db_path)
        response = process_event({**GOOD, "customer": "Другая подпись", "message": "Изменённый текст"}, self.db_path)
        self.assertEqual(response, {"status": "duplicate", "id": first["id"]})
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT customer, message FROM leads WHERE id=?", (first["id"],)).fetchone()
        self.assertEqual(row, (GOOD["customer"], GOOD["message"]))

    def test_duplicate_after_reopening_database(self):
        first = process_event(dict(GOOD), self.db_path)
        # Второй вызов открывает отдельное подключение к той же БД.
        second = process_event(dict(GOOD), self.db_path)
        self.assertEqual(second, {"status": "duplicate", "id": first["id"]})

    def test_non_string_field_is_invalid(self):
        response = process_event({**GOOD, "external_id": 100}, self.db_path)
        self.assertEqual(response["status"], "invalid")
        self.assertEqual(self.count("leads"), 0)


if __name__ == "__main__":
    unittest.main()
