"""백그라운드 작업. 상태의 원본은 jobs 테이블이고, Redis에는 작업 ID와 user_id만 싣는다 (ADR-0001)."""

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from sqlalchemy import FetchedValue, func, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column
from taskiq_redis import RedisStreamBroker

from notree.platform import usage
from notree.platform.db import Base, after_commit, user_tx

log = logging.getLogger(__name__)
broker = RedisStreamBroker(os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"))

MAX_USER_STARTED = 2  # 계정당 사용자가 시작한 작업의 동시 실행 수 (PER-003 5, ADR-0022)


class ConcurrencyLimit(Exception):
    """계정 동시 실행 한도에 걸려 작업을 등록하지 않았다 (PER-003 5)."""


class JobNotRunning(Exception):
    """회수 루프가 이미 실패로 끝낸 작업이다. 결과를 저장하지 않는다."""


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
    user_started: Mapped[bool] = mapped_column(server_default=FetchedValue())
    attempt: Mapped[int] = mapped_column(server_default=FetchedValue())
    error_code: Mapped[str | None]
    run_after: Mapped[datetime] = mapped_column(server_default=FetchedValue())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=FetchedValue())


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    job_id: Mapped[int]
    sent_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=FetchedValue())


Handler = Callable[[Job], Awaitable[None]]
_handlers: dict[str, Handler] = {}
_failure_hooks: dict[str, Handler] = {}


def handler(kind: str) -> Callable[[Handler], Handler]:
    """작업 종류를 처리할 함수를 등록한다. 그 모듈을 notree/worker.py에서 import해야 워커가 안다.

    함수는 트랜잭션 밖에서 불린다. 읽을 때는 user_tx(job.user_id)를, 결과를 저장할 때는 job_tx(job)를 연다.
    """

    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


def on_failure(kind: str) -> Callable[[Handler], Handler]:
    """작업이 실패로 끝났을 때 부를 함수를 등록한다. @handler와 같은 파일에 둔다.

    platform은 모듈의 테이블을 모르므로, 모듈이 여기서 자기 도메인 행을 실패로 바꾼다.
    처리 함수의 예외, 처리 함수 없음, 회수 루프의 stalled 처리 뒤에 트랜잭션 밖에서 불린다.
    회수 루프는 결과 저장이 끝난 작업도 실패로 끝낼 수 있으니, 아직 진행 중인 행만 바꾼다.
    """

    def register(fn: Handler) -> Handler:
        _failure_hooks[kind] = fn
        return fn

    return register


async def enqueue(
    db: AsyncSession,
    kind: str,
    target_id: int | None = None,
    *,
    user_started: bool = False,
) -> Job:
    """작업 행과 전달 기록(outbox)을 넣고, 이 트랜잭션이 커밋되면 워커를 깨운다.

    사용자가 요청해 시작하는 작업은 user_started를 켠다. 계정 동시 실행 한도를 넘으면 ConcurrencyLimit이다.
    """
    user_id: int = db.info["user_id"]
    if user_started:
        # 같은 사용자의 등록을 줄 세운다. 둘이 동시에 세면 둘 다 통과해 한도를 넘는다
        await db.execute(
            text("SELECT 1 FROM users WHERE id = :id FOR NO KEY UPDATE"),
            {"id": user_id},
        )
        started, qa = (
            await db.execute(
                select(
                    func.count().filter(Job.user_started),
                    func.count().filter(Job.kind == "qa_answer"),
                ).where(Job.status.in_(("queued", "running")))
            )
        ).one()
        # Q&A는 유니크 인덱스 jobs_one_qa도 막지만, 그 오류가 나기 전에 한도로 알린다
        if started >= MAX_USER_STARTED or (kind == "qa_answer" and qa > 0):
            raise ConcurrencyLimit(kind)

    job = Job(
        user_id=user_id, kind=kind, target_id=target_id, user_started=user_started
    )
    db.add(job)
    await db.flush()
    outbox = Outbox(user_id=user_id, job_id=job.id)
    db.add(outbox)
    await db.flush()
    after_commit(db, lambda: send_outbox(outbox.id, job.id, user_id))
    return job


async def send_outbox(outbox_id: int, job_id: int, user_id: int) -> None:
    """작업을 큐에 보내고 보냈다고 적는다. 실패해도 예외를 올리지 않는다.

    등록한 요청은 이미 커밋됐고, 보내지 못한 행은 회수 루프가 다시 보낸다 (ADR-0019).
    """
    try:
        await run_job.kiq(job_id, user_id)
        async with user_tx(user_id) as db:
            await db.execute(
                update(Outbox).where(Outbox.id == outbox_id).values(sent_at=func.now())
            )
    except Exception as e:  # noqa: BLE001  무엇이 실패해도 올리지 않는다. 로그에는 ID와 예외 종류만 남긴다 (SER-001)
        log.warning(
            "outbox %s (job %s) not sent: %s", outbox_id, job_id, type(e).__name__
        )


@asynccontextmanager
async def job_tx(job: Job) -> AsyncIterator[AsyncSession]:
    """처리 함수가 결과를 저장할 때 쓰는 트랜잭션. 작업이 running이 아니면 JobNotRunning이다.

    회수 루프가 실패로 끝낸 뒤 늦게 깨어난 워커의 저장을 막는다 (docs/schema-mvp.md '늦은 저장 막기').
    행을 잠가 두므로 이 트랜잭션이 끝날 때까지 회수 루프가 이 작업을 끝내지 못한다.
    """
    async with user_tx(job.user_id) as db:
        status = await db.scalar(
            select(Job.status).where(Job.id == job.id).with_for_update()
        )
        if status != "running":
            raise JobNotRunning(job.id)
        yield db


async def run_failure_hook(job: Job) -> None:
    """실패로 끝난 작업의 실패 훅을 부른다. 훅이 없으면 아무것도 하지 않는다."""
    # shortcut: 작업을 실패로 끝낸 뒤 훅을 부르기 전에 죽으면 도메인 행이 진행 중으로 남는다,
    #   완료·실패 이벤트를 outbox에 얹을 때 고친다 (ADR-0019)
    hook = _failure_hooks.get(job.kind)
    if hook is None:
        return
    try:
        await hook(job)
    except Exception as e:  # noqa: BLE001  훅의 예외 메시지에는 원문이 섞일 수 있어 ID와 예외 종류만 남긴다 (SER-001)
        log.error(
            "job %s (%s) failure hook failed: %s", job.id, job.kind, type(e).__name__
        )


# shortcut: 재시도·인계·실행 시도 번호(fencing)가 없다. 워커가 도중에 죽으면 회수 루프(sweeper.py)가
#   실패로 끝내고 사용자가 재시도한다, 사용자 재시도 없이 이어서 끝내야 할 때 ADR-0018대로 만든다.
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
        except JobNotRunning:
            # 늦은 저장이다. 회수 루프가 이미 실패로 끝내고 실패 훅도 불렀다.
            # 아래 갱신은 running 조건에 걸려 상태를 바꾸지 않고, 훅도 다시 부르지 않는다
            pass
        except Exception as e:
            # shortcut: 예외 메시지에 원문이 섞일 수 있다, 운영 로그를 붙일 때 원문 필터를 건다 (SER-001)
            log.exception("job %s (%s) failed", job_id, job.kind)
            error = type(e).__name__

    async with user_tx(user_id) as db:
        # running일 때만 끝낸다. 회수 루프가 먼저 failed로 끝낸 작업을 succeeded로 덮지 않는다
        finished = await db.scalar(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(
                status="failed" if error else "succeeded",
                error_code=error,
                finished_at=func.now(),
            )
            .returning(Job)
        )
        # 늦게 깨어난 실행이 회수 뒤에 잡은 예약도 있으므로, 이 실행이 끝냈는지와 상관없이 푼다
        await usage.release_job(db, job_id)
    if finished is not None and error:
        await run_failure_hook(finished)
