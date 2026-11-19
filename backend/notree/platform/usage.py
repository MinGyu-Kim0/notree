"""AI 비용 예약과 정산 (PER-003 2). 호출 전에 reserve로 예약하고 호출 뒤에 settle로 정산한다."""

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import FetchedValue, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from notree.platform.db import Base

# 하루 한도(UTC). 실제 요금을 확인하기 전의 설정 기본값이다 (PER-003 2)
USER_DAILY_USD = Decimal(1)
GLOBAL_DAILY_USD = Decimal(10)
_GLOBAL_LOCK = 3003  # 전체 한도 확인을 줄 세우는 advisory lock 키. 다른 곳과 겹치지 않으면 되는 임의의 수


class BudgetExceeded(Exception):
    """하루 비용 한도에 닿았다. 인자는 걸린 한도('user' 또는 'global')다."""


class UsageLedger(Base):
    __tablename__ = "usage_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    job_id: Mapped[int | None]
    provider: Mapped[str]
    utc_date: Mapped[date]
    reserved_usd: Mapped[Decimal]
    cost_usd: Mapped[Decimal | None]
    status: Mapped[str] = mapped_column(server_default=FetchedValue())
    created_at: Mapped[datetime] = mapped_column(server_default=FetchedValue())


async def reserve(
    db: AsyncSession,
    usd: Decimal,
    *,
    provider: str = "openai",
    job_id: int | None = None,
) -> int:
    """AI 호출 전에 예상 비용을 예약하고 장부 ID를 돌려준다. 한도를 넘으면 BudgetExceeded다.

    job_id가 남의 작업이거나 없는 작업이면 LookupError다.
    사용액은 오늘 정산된 비용에 아직 풀리지 않은 예약을 더한 값이다. 예약은 날짜가 바뀌어도 남는다.
    """
    user_id: int = db.info["user_id"]
    today = datetime.now(UTC).date()
    # FK는 작업이 이 사용자의 것인지 보지 않는다. RLS로 걸러 읽히는 작업에만 예약을 붙인다.
    # 남의 작업에 붙으면 그 작업이 끝날 때 이 예약이 함께 풀려 한도 계산이 틀어진다
    if job_id is not None and not await db.scalar(
        text("SELECT true FROM jobs WHERE id = :id"), {"id": job_id}
    ):
        raise LookupError(f"job {job_id}")
    # 같은 사용자의 예약을 줄 세운다. 둘이 동시에 확인하면 둘 다 통과해 한도를 넘는다
    await db.execute(
        text("SELECT 1 FROM users WHERE id = :id FOR NO KEY UPDATE"), {"id": user_id}
    )
    # global_spend 함수와 같은 식이다. RLS가 이 사용자의 행만 더한다
    user_spend: Decimal = await db.scalar(
        text(
            "SELECT coalesce(sum(cost_usd) FILTER"
            " (WHERE status = 'settled' AND utc_date = :today), 0)"
            " + coalesce(sum(reserved_usd) FILTER (WHERE status = 'held'), 0)"
            " FROM usage_ledger"
        ),
        {"today": today},
    )
    if user_spend + usd > USER_DAILY_USD:
        raise BudgetExceeded("user")

    # 전체 합계는 다른 사용자의 행이라 RLS 밖의 함수로 읽고, 사용자 잠금으로는 못 막으니 따로 줄 세운다
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _GLOBAL_LOCK})
    global_spend: Decimal = await db.scalar(
        text("SELECT global_spend(:today)"), {"today": today}
    )
    if global_spend + usd > GLOBAL_DAILY_USD:
        raise BudgetExceeded("global")

    entry = UsageLedger(
        user_id=user_id,
        job_id=job_id,
        provider=provider,
        utc_date=today,
        reserved_usd=usd,
    )
    db.add(entry)
    await db.flush()
    return entry.id


async def settle(db: AsyncSession, ledger_id: int, cost_usd: Decimal) -> None:
    """AI 호출 뒤에 예약을 실제 비용으로 정산한다."""
    # 상태를 가리지 않는다. 회수 루프가 먼저 풀어 버린 예약이라도 호출이 실제로 일어났으면 비용을 센다
    await db.execute(
        update(UsageLedger)
        .where(UsageLedger.id == ledger_id)
        .values(status="settled", cost_usd=cost_usd)
    )


async def release_job(db: AsyncSession, job_id: int) -> None:
    """작업이 정산하지 못하고 남긴 예약을 푼다. 풀지 않으면 날짜가 바뀌어도 한도를 계속 잡는다."""
    await db.execute(
        update(UsageLedger)
        .where(UsageLedger.job_id == job_id, UsageLedger.status == "held")
        .values(status="released")
    )
