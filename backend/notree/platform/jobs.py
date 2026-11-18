"""백그라운드 작업. 상태의 원본은 jobs 테이블이고, Redis에는 작업 ID와 user_id만 싣는다 (ADR-0001)."""

import logging
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from sqlalchemy import FetchedValue, func, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from taskiq_redis import RedisStreamBroker

from notree.platform.db import Base, after_commit, user_tx

log = logging.getLogger(__name__)
broker = RedisStreamBroker(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"))


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    kind: Mapped[str]
    status: Mapped[str] = mapped_column(server_default=FetchedValue())
    target_id: Mapped[int | None]
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=FetchedValue()
    )
    attempt: Mapped[int] = mapped_column(server_default=FetchedValue())
    error_code: Mapped[str | None]
    run_after: Mapped[datetime] = mapped_column(server_default=FetchedValue())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=FetchedValue())


Handler = Callable[[Job], Awaitable[None]]
_handlers: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    """작업 종류를 처리할 함수를 등록한다. 그 모듈을 notree/worker.py에서 import해야 워커가 안다.

    함수는 트랜잭션 밖에서 불린다. 필요한 곳에서 user_tx(job.user_id)를 직접 연다.
    """

    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


async def enqueue(db: AsyncSession, kind: str, target_id: int | None = None) -> Job:
    """작업 행을 넣고, 이 트랜잭션이 커밋되면 워커를 깨운다."""
    user_id: int = db.info["user_id"]
    job = Job(user_id=user_id, kind=kind, target_id=target_id)
    db.add(job)
    await db.flush()
    after_commit(db, lambda: run_job.kiq(job.id, user_id))
    return job


# shortcut: 재시도·회수·실행 권한(fencing)이 없다. 워커가 도중에 죽으면 행이 running으로 남는다.
#   장애 시험(docs/testing/failure-matrix.md)을 돌릴 때 ADR-0018·0019대로 만든다.
@broker.task
async def run_job(job_id: int, user_id: int) -> None:
    async with user_tx(user_id) as db:
        job = await db.scalar(
            update(Job)
            .where(Job.id == job_id, Job.status == "queued")
            .values(status="running", attempt=Job.attempt + 1, started_at=func.now())
            .returning(Job)
        )
    if job is None:
        return  # 이미 처리했거나 취소된 작업

    error = None
    fn = _handlers.get(job.kind)
    if fn is None:
        error = "no_handler"
    else:
        try:
            await fn(job)
        except Exception as e:
            # shortcut: 예외 메시지에 원문이 섞일 수 있다, 운영 로그를 붙일 때 원문 필터를 건다 (SER-001)
            log.exception("job %s (%s) failed", job_id, job.kind)
            error = type(e).__name__

    async with user_tx(user_id) as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(
                status="failed" if error else "succeeded",
                error_code=error,
                finished_at=func.now(),
            )
        )
