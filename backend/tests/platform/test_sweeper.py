"""회수 루프 (docs/schema-mvp.md '작업 전달과 멈춘 작업')."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete

from notree.platform.db import user_tx
from notree.platform.jobs import Job, Outbox, on_failure
from notree.platform.sweeper import sweep_once
from notree.platform.usage import UsageLedger
from tests.conftest import login

pytestmark = pytest.mark.anyio


@pytest.fixture
async def user_id() -> AsyncIterator[int]:
    """작업이 없는 테스트 사용자.

    sweep_once는 DB 전체를 훑으므로 큐 전송을 가로채지 않고 REDIS_URL의 Redis로 실제로 보낸다.
    가로채면 같은 DB에 있는 남의 미전송 행까지 보내지 않고 보냈다고 적게 된다.
    """
    user_id = await login("test-sweeper")
    async with user_tx(user_id) as db:
        await db.execute(
            delete(Job)
        )  # RLS가 이 사용자의 작업만 지운다. outbox는 CASCADE
    yield user_id
    async with user_tx(user_id) as db:
        await db.execute(delete(Job))


async def test_resends_old_unsent_outbox(user_id: int) -> None:
    now = datetime.now(UTC)
    old = now - timedelta(minutes=1)
    async with user_tx(user_id) as db:
        job = Job(user_id=user_id, kind="purge")
        db.add(job)
        await db.flush()
        lost = Outbox(user_id=user_id, job_id=job.id, created_at=old)
        fresh = Outbox(user_id=user_id, job_id=job.id)  # enqueue가 곧 보낼 행
        sent = Outbox(user_id=user_id, job_id=job.id, created_at=old, sent_at=old)
        db.add_all([lost, fresh, sent])

    await sweep_once()

    async with user_tx(user_id) as db:
        lost, fresh, sent = [
            await db.get_one(Outbox, row.id) for row in (lost, fresh, sent)
        ]
    assert lost.sent_at is not None and lost.sent_at >= now
    assert fresh.sent_at is None
    assert sent.sent_at == old


async def test_fails_stalled_jobs(user_id: int) -> None:
    hooked: list[int] = []

    @on_failure("qa_answer")
    async def mark_failed(job: Job) -> None:
        hooked.append(job.id)

    started = datetime.now(UTC) - timedelta(
        minutes=5
    )  # Q&A 기준은 넘고 배경 작업 기준은 안 넘는다
    async with user_tx(user_id) as db:
        qa = Job(
            user_id=user_id, kind="qa_answer", status="running", started_at=started
        )
        background = Job(
            user_id=user_id, kind="final_note", status="running", started_at=started
        )
        db.add_all([qa, background])
        await db.flush()
        hold = UsageLedger(
            user_id=user_id,
            job_id=qa.id,
            provider="openai",
            utc_date=started.date(),
            reserved_usd=Decimal("0.000001"),
        )
        db.add(hold)

    await sweep_once()

    async with user_tx(user_id) as db:
        qa = await db.get_one(Job, qa.id)
        background = await db.get_one(Job, background.id)
        hold = await db.get_one(UsageLedger, hold.id)
    assert (qa.status, qa.error_code) == ("failed", "stalled")
    assert qa.finished_at is not None
    assert background.status == "running"
    assert hold.status == "released"
    # 같은 DB에 멈춘 남의 Q&A가 있으면 그것도 함께 온다
    assert qa.id in hooked and background.id not in hooked
