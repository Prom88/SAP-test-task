"""Небольшой учебный обработчик заявок. Некоторые сценарии реализованы с ошибками.

Тестовое задание САП КОД. Используются только синтетические данные.
"""

import sqlite3


def _prepare_db(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            customer TEXT NOT NULL,
            message TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL
        );
        """
    )


def process_event(event: dict, db_path: str) -> dict:
    """Принимает событие и возвращает dict со статусом и, при успехе, id заявки.

    Контракт статусов и бизнес-правила описаны в README.md.
    """
    with sqlite3.connect(db_path) as connection:
        _prepare_db(connection)

        source = event.get("source", "")
        external_id = event.get("external_id", "")
        customer = event.get("customer", "")
        message = event.get("message", "")

        cursor = connection.execute(
            """
            INSERT INTO leads (source, external_id, customer, message)
            VALUES (?, ?, ?, ?)
            """,
            (source, external_id, customer, message),
        )
        lead_id = cursor.lastrowid
        connection.execute(
            "INSERT INTO notifications (lead_id) VALUES (?)", (lead_id,)
        )
        connection.commit()
        return {"status": "created", "id": lead_id}
