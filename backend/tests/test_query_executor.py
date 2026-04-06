from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.query_executor import execute_query_postgres


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self._idx = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._idx >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._idx]
        self._idx += 1
        return row


class _FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_execute_query_postgres_uses_cursor_and_truncates():
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="SET")
    conn.fetch = AsyncMock(side_effect=AssertionError("fetch() must not be used"))
    conn.transaction.return_value = _FakeTransaction()
    conn.cursor.return_value = _FakeCursor(
        [
            {"id": 1, "name": "a"},
            {"id": 2, "name": "b"},
            {"id": 3, "name": "c"},
        ]
    )
    conn.close = AsyncMock()

    with patch("app.db.query_executor.asyncpg.connect", new=AsyncMock(return_value=conn)):
        result = await execute_query_postgres(
            host="localhost",
            port=5432,
            database="db",
            username="user",
            password="pw",
            sql="SELECT id, name FROM t",
            max_rows=2,
            query_timeout=30,
            ssl_mode="disable",
        )

    assert result.columns == ["id", "name"]
    assert result.row_count == 2
    assert result.truncated is True
    assert [r["id"] for r in result.rows] == [1, 2]
    conn.fetch.assert_not_called()
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_query_postgres_empty_result():
    conn = MagicMock()
    conn.execute = AsyncMock(return_value="SET")
    conn.fetch = AsyncMock(side_effect=AssertionError("fetch() must not be used"))
    conn.transaction.return_value = _FakeTransaction()
    conn.cursor.return_value = _FakeCursor([])
    conn.close = AsyncMock()

    with patch("app.db.query_executor.asyncpg.connect", new=AsyncMock(return_value=conn)):
        result = await execute_query_postgres(
            host="localhost",
            port=5432,
            database="db",
            username="user",
            password="pw",
            sql="SELECT id FROM t",
            max_rows=100,
            query_timeout=30,
            ssl_mode="disable",
        )

    assert result.columns == []
    assert result.rows == []
    assert result.row_count == 0
    conn.fetch.assert_not_called()
    conn.close.assert_awaited_once()
