"""Небольшой учебный обработчик заявок. Некоторые сценарии реализованы с ошибками.

Тестовое задание САП КОД. Используются только синтетические данные.
"""

import sqlite3
from contextlib import closing


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


def _validate_event(event: dict) -> tuple[dict[str, str] | None, str | None]:
    if not isinstance(event, dict):
        return None, "Событие должно быть словарём"

    fields: dict[str, str] = {}
    for name in ("source", "external_id", "customer", "message"):
        value = event.get(name)
        if not isinstance(value, str):
            return None, f"Поле '{name}' должно быть строкой"
        if not value.strip():
            return None, f"Поле '{name}' не должно быть пустым"
        # Нормализованное значение используется при поиске дубликатов и сохранении.
        fields[name] = value.strip()
    return fields, None


def process_event(event: dict, db_path: str) -> dict:
    """Принимает событие и возвращает dict со статусом и, при успехе, id заявки.

    Контракт статусов и бизнес-правила описаны в README.md.
    """
    fields, reason = _validate_event(event)
    if fields is None:
        return {"status": "invalid", "reason": reason}

    with closing(sqlite3.connect(db_path)) as connection:
        _prepare_db(connection)
        # Блокируем конкурирующие вызовы, чтобы два повтора не создали отдельные заявки.
        connection.execute("BEGIN IMMEDIATE")

        source = fields["source"]
        external_id = fields["external_id"]
        customer = fields["customer"]
        message = fields["message"]

        existing = connection.execute(
            "SELECT id FROM leads WHERE source = ? AND external_id = ? ORDER BY id LIMIT 1",
            (source, external_id),
        ).fetchone()
        if existing is not None:
            connection.commit()
            # Сохраняем исходные данные заявки и не создаём повторное уведомление.
            return {"status": "duplicate", "id": existing[0]}

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
