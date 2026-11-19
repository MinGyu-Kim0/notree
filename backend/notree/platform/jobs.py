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
FailureHook = Callable[[AsyncSession, Job], Awaitable[None]]
SlotCounter = Callable[[AsyncSession], Awaitable[int]]
_handlers: dict[str, Handler] = {}
_failure_hooks: dict[str, FailureHook] = {}
_slot_counters: list[SlotCounter] = []


def handler(kind: str) -> Callable[[Handler], Handler]:
    """작업 종류를 처리할 함수를 등록한다. 그 모듈을 notree/worker.py에서 import해야 워커가 안다.

    함수는 트랜잭션 밖에서 불린다. 읽을 때는 user_tx(job.user_id)를, 결과를 저장할 때는 job_tx(job)를 연다.
    """

    def register(fn: Handler) -> Handler:
        _handlers[kind] = fn
        return fn

    return register


def on_failure(kind: str) -> Callable[[FailureHook], FailureHook]:
    """작업이 실패로 끝났을 때 부를 함수를 등록한다. @handler와 같은 파일에 둔다.

    platform은 모듈의 테이블을 모르므로, 모듈이 여기서 자기 도메인 행을 실패로 바꾼다.
    jobs를 failed로 바꾸는 트랜잭션(db) 안에서 불린다. 훅이 예외를 내면 실패 처리 전체가 롤백되고
    작업은 running으로 남아, 회수 루프가 다음에 다시 끝낸다.
    회수 루프는 결과 저장이 끝난 작업도 실패로 끝낼 수 있으니, 아직 진행 중인 행만 바꾼다.
    """

    def register(fn: FailureHook) -> FailureHook:
        _failure_hooks[kind] = fn
        return fn

    return register


def counts_toward_limit(fn: SlotCounter) -> SlotCounter:
    """작업이 아니면서 계정 동시 실행 한도에 드는 것(진행 중인 녹음)을 세는 함수를 등록한다 (PER-003 5).

    platform은 다른 모듈의 테이블을 읽을 수 없어서, 그 테이블을 가진 모듈이 자기 db.py에서 등록한다.
    """
    _slot_counters.append(fn)
    return fn


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
        started = await user_started_count(db)
        qa = await db.scalar(
            select(func.count()).where(
                Job.kind == "qa_answer", Job.status.in_(("queued", "running"))
            )
        )
        # Q&A는 유니크 인덱스 jobs_one_qa도 막지만, 그 오류가 나기 전에 한도로 알린다
        if started >= MAX_USER_STARTED or (kind == "qa_answer" and qa):
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


async def user_started_count(db: AsyncSession) -> int:
    """계정 동시 실행 한도에 드는 수: 끝나지 않은 사용자 시작 작업 + 등록된 함수가 센 것(진행 중인 녹음) (PER-003 5).

    users 행을 잠가 같은 사용자의 작업 등록과 녹음 시작을 줄 세운다. 둘이 동시에 세면 둘 다 통과해 한도를 넘는다.
    녹음 시작도 같은 트랜잭션에서 이 값을 보고 MAX_USER_STARTED 이상이면 막는다.
    """
    await db.execute(
        text("SELECT 1 FROM users WHERE id = :id FOR NO KEY UPDATE"),
        {"id": db.info["user_id"]},
    )
    count = (
        await db.scalar(
            select(func.count()).where(
                Job.user_started, Job.status.in_(("queued", "running"))
            )
        )
        or 0
    )
    for counter in _slot_counters:
        count += await counter(db)
    return count


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


async def fail_job(db: AsyncSession, job_id: int, error_code: str) -> Job | None:
    """running인 작업을 실패로 끝내고, 예약을 풀고, 실패 훅을 같은 트랜잭션에서 부른다.

    셋이 한 트랜잭션이라 중간에 죽거나 훅이 실패해도 작업은 running으로 남고, 회수 루프가 다시 끝낸다.
    이미 끝난 작업이면 아무것도 하지 않고 None이다.
    """
    job: Job | None = await db.scalar(
        update(Job)
        .where(Job.id == job_id, Job.status == "running")
        .values(status="failed", error_code=error_code, finished_at=func.now())
        .returning(Job)
    )
    if job is None:
        return None
    await usage.release_job(db, job_id)
    hook = _failure_hooks.get(job.kind)
    if hook is not None:
        await hook(db, job)
    return job


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
        except Exception as e:  # noqa: BLE001  처리 함수의 어떤 예외든 작업 실패로 남긴다
            # 예외 메시지와 traceback의 값에는 원문이 섞일 수 있어 ID와 예외 종류만 남긴다 (SER-001 2)
            error = type(e).__name__
            log.error("job %s (%s) failed: %s", job_id, job.kind, error)

    if error:
        try:
            async with user_tx(user_id) as db:
                if await fail_job(db, job_id, error) is None:
                    # 회수 루프가 이미 끝낸 작업이다. 훅은 부르지 않고, 이 실행이 늦게 잡은 예약만 푼다
                    await usage.release_job(db, job_id)
        except Exception as e:  # noqa: BLE001  훅이 실패하면 작업은 running으로 남고 회수 루프가 다시 끝낸다
            log.error(
                "job %s (%s) failure handling failed: %s",
                job_id,
                job.kind,
                type(e).__name__,
            )
        return

    async with user_tx(user_id) as db:
        # running일 때만 끝낸다. 회수 루프가 먼저 failed로 끝낸 작업을 succeeded로 덮지 않는다
        await db.execute(
            update(Job)
            .where(Job.id == job_id, Job.status == "running")
            .values(status="succeeded", finished_at=func.now())
        )
        # 늦게 깨어난 실행이 회수 뒤에 잡은 예약도 있으므로, 이 실행이 끝냈는지와 상관없이 푼다
        await usage.release_job(db, job_id)
