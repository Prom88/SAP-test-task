"""Additional tests for source-scoped lead identity."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from inspect import signature
from pathlib import Path

from app import process_event


GOOD: dict[str, str] = {
    "source": "telegram",
    "external_id": "event-100",
    "customer": "Учебный клиент",
    "message": "Нужна доставка в Казань",
}


class LeadIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmp.name) / "leads.sqlite3")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_retry_returns_existing_id_and_does_not_add_notification(self) -> None:
        first = process_event(dict(GOOD), self.db_path)
        second = process_event(dict(GOOD), self.db_path)

        self.assertEqual(second, {"status": "duplicate", "id": first["id"]})
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)

    def test_same_external_id_from_another_source_is_new(self) -> None:
        first = process_event(dict(GOOD), self.db_path)
        second = process_event({**GOOD, "source": "max"}, self.db_path)

        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "created")
        self.assertNotEqual(first["id"], second["id"])

    def test_new_pair_creates_one_lead_and_one_notification(self) -> None:
        result = process_event(dict(GOOD), self.db_path)

        self.assertEqual(result["status"], "created")
        self.assertIsInstance(result["id"], int)
        self.assertGreater(result["id"], 0)
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 1)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0], 1)

    def test_invalid_fields_return_reason_without_creating_database(self) -> None:
        invalid_events = [
            {**GOOD, field: "  "}
            for field in ("source", "external_id", "customer", "message")
        ]
        invalid_events.extend(
            {**GOOD, field: None}
            for field in ("source", "external_id", "customer", "message")
        )
        invalid_events.extend(
            {key: value for key, value in GOOD.items() if key != field}
            for field in ("source", "external_id", "customer", "message")
        )
        invalid_events.append([])

        for event in invalid_events:
            with self.subTest(event=event):
                result = process_event(event, self.db_path)
                self.assertEqual(result["status"], "invalid")
                self.assertTrue(result["reason"])
                self.assertFalse(Path(self.db_path).exists())

    def test_all_fields_are_trimmed_before_storage_and_comparison(self) -> None:
        padded = {key: f"  {value}  " for key, value in GOOD.items()}
        first = process_event(padded, self.db_path)
        second = process_event(dict(GOOD), self.db_path)

        self.assertEqual(first["status"], "created")
        self.assertEqual(second, {"status": "duplicate", "id": first["id"]})
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT source, external_id, customer, message FROM leads WHERE id = ?",
                (first["id"],),
            ).fetchone()
        self.assertEqual(row, tuple(GOOD.values()))

    def test_source_comparison_preserves_case(self) -> None:
        first = process_event(dict(GOOD), self.db_path)
        second = process_event({**GOOD, "source": "Telegram"}, self.db_path)

        self.assertEqual(first["status"], "created")
        self.assertEqual(second["status"], "created")
        self.assertNotEqual(first["id"], second["id"])

    def test_records_persist_after_process_connection_closes(self) -> None:
        result = process_event(dict(GOOD), self.db_path)

        with closing(sqlite3.connect(self.db_path)) as connection:
            lead = connection.execute(
                "SELECT source, external_id, customer, message FROM leads WHERE id = ?",
                (result["id"],),
            ).fetchone()
            notification_count = connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE lead_id = ?",
                (result["id"],),
            ).fetchone()[0]

        self.assertEqual(lead, tuple(GOOD.values()))
        self.assertEqual(notification_count, 1)

    def test_retry_with_changed_text_preserves_first_lead_data(self) -> None:
        first = process_event(dict(GOOD), self.db_path)
        retry = {
            **GOOD,
            "customer": "Другой клиент",
            "message": "Изменённый текст",
        }

        result = process_event(retry, self.db_path)

        self.assertEqual(result, {"status": "duplicate", "id": first["id"]})
        with closing(sqlite3.connect(self.db_path)) as connection:
            row = connection.execute(
                "SELECT customer, message FROM leads WHERE id = ?",
                (first["id"],),
            ).fetchone()
            notification_count = connection.execute(
                "SELECT COUNT(*) FROM notifications WHERE lead_id = ?",
                (first["id"],),
            ).fetchone()[0]
        self.assertEqual(row, (GOOD["customer"], GOOD["message"]))
        self.assertEqual(notification_count, 1)

    def test_public_signature_and_database_schema_remain_compatible(self) -> None:
        self.assertEqual(
            tuple(signature(process_event).parameters),
            ("event", "db_path"),
        )
        process_event(dict(GOOD), self.db_path)

        with closing(sqlite3.connect(self.db_path)) as connection:
            leads_columns = tuple(
                row[1] for row in connection.execute("PRAGMA table_info(leads)")
            )
            notification_columns = tuple(
                row[1]
                for row in connection.execute("PRAGMA table_info(notifications)")
            )

        self.assertEqual(
            leads_columns,
            ("id", "source", "external_id", "customer", "message"),
        )
        self.assertEqual(notification_columns, ("id", "lead_id"))
