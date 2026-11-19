"""비용 예약과 정산 (PER-003 2)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import delete, text, update

from notree.platform import usage
from notree.platform.db import user_tx
from notree.platform.jobs import Job
from notree.platform.usage import BudgetExceeded, UsageLedger, reserve, settle
from tests.conftest import login

pytestmark = pytest.mark.anyio


async def void_ledger(user_id: int) -> None:
    """앱 계정은 장부를 지울 수 없다. 남은 행을 released로 바꿔 사용자·전체 한도 계산에서 뺀다."""
    async with user_tx(user_id) as db:
        await db.execute(
            update(UsageLedger)
            .where(UsageLedger.status != "released")
            .values(status="released", cost_usd=None)
        )


@pytest.fixture
async def users(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[tuple[int, int]]:
    """쓴 금액이 0인 테스트 사용자 둘.

    전체 한도는 같은 DB를 쓰는 다른 사용자의 장부에 따라 달라지므로 기본으로 꺼 둔다.
    """
    monkeypatch.setattr(usage, "GLOBAL_DAILY_USD", Decimal(10**6))
    ids = (await login("test-usage-a"), await login("test-usage-b"))
    for user_id in ids:
        await void_ledger(user_id)
    yield ids
    for user_id in ids:
        await void_ledger(user_id)


async def test_reserve_then_settle(users: tuple[int, int]) -> None:
    user_id, _ = users
    async with user_tx(user_id) as db:
        ledger_id = await reserve(db, Decimal("0.4"))
        await settle(db, ledger_id, Decimal("0.1"))
        row = await db.get_one(UsageLedger, ledger_id, populate_existing=True)
        assert (row.status, row.cost_usd, row.provider) == (
            "settled",
            Decimal("0.1"),
            "openai",
        )
        # 정산하면 예약액 0.4가 아니라 실제 비용 0.1만 남는다. 0.9를 더 예약하면 한도 1에 꼭 맞는다
        await reserve(db, Decimal("0.9"))


async def test_user_limit(users: tuple[int, int]) -> None:
    user_id, _ = users
    async with user_tx(user_id) as db:
        await reserve(db, Decimal("0.6"))
    with pytest.raises(BudgetExceeded):
        async with user_tx(user_id) as db:
            await reserve(db, Decimal("0.6"))


async def test_concurrent_reserves_stay_within_limit(users: tuple[int, int]) -> None:
    user_id, _ = users

    async def try_reserve() -> bool:
        try:
            async with user_tx(user_id) as db:
                await reserve(db, Decimal("0.3"))
        except BudgetExceeded:
            return False
        return True

    assert sum(await asyncio.gather(*(try_reserve() for _ in range(5)))) == 3


async def test_hold_outlives_its_day(users: tuple[int, int]) -> None:
    user_id, _ = users
    yesterday = datetime.now(UTC).date() - timedelta(days=1)
    async with user_tx(user_id) as db:
        db.add_all(
            [
                UsageLedger(
                    user_id=user_id,
                    provider="openai",
                    utc_date=yesterday,
                    reserved_usd=Decimal("0.6"),
                ),
                UsageLedger(  # 어제 정산된 비용은 오늘 한도에 들어가지 않는다
                    user_id=user_id,
                    provider="openai",
                    utc_date=yesterday,
                    reserved_usd=Decimal("0.6"),
                    cost_usd=Decimal("0.6"),
                    status="settled",
                ),
            ]
        )

    with pytest.raises(BudgetExceeded):
        async with user_tx(user_id) as db:
            await reserve(db, Decimal("0.5"))
    async with user_tx(user_id) as db:
        await reserve(db, Decimal("0.4"))


async def test_other_users_spend_is_not_mine(users: tuple[int, int]) -> None:
    user_id, other_id = users
    async with user_tx(other_id) as db:
        await reserve(db, Decimal("0.9"))
    async with user_tx(user_id) as db:
        await reserve(db, Decimal("0.9"))


async def test_global_limit_across_users(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with user_tx(users[0]) as db:
        spent: Decimal = await db.scalar(
            text("SELECT global_spend(:today)"), {"today": datetime.now(UTC).date()}
        )
    monkeypatch.setattr(usage, "GLOBAL_DAILY_USD", spent + Decimal("0.7"))

    async def try_reserve(user_id: int) -> bool:
        try:
            async with user_tx(user_id) as db:
                await reserve(db, Decimal("0.3"))
        except BudgetExceeded:
            return False
        return True

    # 사용자 한도로는 넷 다 들어가지만 전체 한도에는 둘만 들어간다. 두 사용자가 동시에 확인해도 그렇다
    assert sum(await asyncio.gather(*(try_reserve(u) for u in users * 2))) == 2


async def test_release_job_frees_only_that_jobs_holds(users: tuple[int, int]) -> None:
    user_id, _ = users
    async with user_tx(user_id) as db:
        job = Job(user_id=user_id, kind="purge")
        db.add(job)
        await db.flush()
        await reserve(db, Decimal("0.6"), job_id=job.id)
        await reserve(db, Decimal("0.3"))
    try:
        async with user_tx(user_id) as db:
            await usage.release_job(db, job.id)
            await reserve(db, Decimal("0.7"))  # 풀린 0.6 자리에 들어간다
        with pytest.raises(BudgetExceeded):  # 작업에 묶이지 않은 0.3은 그대로다
            async with user_tx(user_id) as db:
                await reserve(db, Decimal("0.01"))
    finally:
        async with user_tx(user_id) as db:
            await db.execute(delete(Job).where(Job.id == job.id))
