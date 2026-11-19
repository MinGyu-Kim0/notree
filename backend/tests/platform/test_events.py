"""화면으로 보내는 이벤트: publish한 것을 stream이 SSE 형식으로 낸다 (ADR-0005)."""

import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import aclosing
from typing import Any

import anyio
import pytest

from notree.platform import events
from notree.platform.events import publish, stream
from tests.conftest import login

pytestmark = pytest.mark.anyio


@pytest.fixture
async def users() -> AsyncIterator[tuple[int, int]]:
    a, b = await login("test-a"), await login("test-b")
    yield a, b
    await events.redis.delete(f"events:{a}", f"events:{b}")


async def frame(frames: AsyncGenerator[str, None]) -> str:
    with anyio.fail_after(5):  # 이벤트가 오지 않으면 매달리지 않고 실패한다
        return await anext(frames)


async def receive(
    frames: AsyncGenerator[str, None],
) -> tuple[str | None, str, Any]:  # Any: 이벤트마다 data 모양이 다르다
    """다음 이벤트를 (id, event, data)로 돌려준다."""
    raw = await frame(frames)
    assert raw.endswith("\n\n")
    fields = dict(line.split(": ", 1) for line in raw.splitlines() if line)
    return fields.get("id"), fields["event"], json.loads(fields["data"])


async def test_stream_sends_events_after_last_event_id(users: tuple[int, int]) -> None:
    a, _ = users
    first = await publish(a, "progress", {"job_id": 1})
    second = await publish(a, "token", {"job_id": 1, "text": "안녕"})
    third = await publish(a, "done", {"job_id": 1})
    async with aclosing(stream(a, first)) as frames:
        assert await receive(frames) == (second, "token", {"job_id": 1, "text": "안녕"})
        assert await receive(frames) == (third, "done", {"job_id": 1})


async def test_stream_without_last_event_id_starts_from_now(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "KEEPALIVE_MS", 50)
    a, _ = users
    before = await publish(a, "token", {"text": "접속 전"})
    async with aclosing(stream(a, None)) as frames:
        # 이벤트를 받기 전에 끊겨도 이어 받을 수 있게, 지금 위치부터 알려 준다
        assert await frame(frames) == f"id: {before}\n\n"
        # 접속 전 이벤트는 오지 않고, 조용하면 주석 줄로 연결을 유지한다
        assert await frame(frames) == ": keepalive\n\n"
        new = await publish(a, "token", {"text": "접속 후"})
        assert await receive(frames) == (new, "token", {"text": "접속 후"})


async def test_reload_comes_first_when_events_were_trimmed(
    users: tuple[int, int],
) -> None:
    a, _ = users
    first = await publish(a, "token", {})
    for n in range(1200):  # 약 1000건만 남으므로 first가 잘려 나간다
        await publish(a, "token", {"n": n})
    async with aclosing(stream(a, first)) as frames:
        assert await receive(frames) == (None, "reload", {})
        new = await publish(a, "done", {})
        assert await receive(frames) == (new, "done", {})  # 남은 옛 이벤트는 건너뛴다


async def test_reload_when_stream_is_empty(users: tuple[int, int]) -> None:
    a, _ = users  # Redis 데이터를 잃은 뒤의 재접속
    async with aclosing(stream(a, "1700000000000-0")) as frames:
        assert await receive(frames) == (None, "reload", {})


@pytest.mark.parametrize("last_event_id", ["abc", "$", "1-2-3", "1700000000000-0"])
async def test_reload_when_last_event_id_is_malformed_or_unknown(
    users: tuple[int, int], last_event_id: str
) -> None:
    a, _ = users
    await publish(a, "token", {})
    async with aclosing(stream(a, last_event_id)) as frames:
        assert await receive(frames) == (None, "reload", {})


async def test_other_users_events_do_not_arrive(users: tuple[int, int]) -> None:
    a, b = users
    first = await publish(a, "token", {})
    await publish(b, "token", {"owner": "b"})
    mine = await publish(a, "token", {"owner": "a"})
    async with aclosing(stream(a, first)) as frames:
        assert await receive(frames) == (mine, "token", {"owner": "a"})
