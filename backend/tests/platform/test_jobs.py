"""작업 등록·전달·실패 처리 (docs/schema-mvp.md '작업 전달과 멈춘 작업')."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

import notree.capture.db  # noqa: F401  녹음 수를 세는 함수를 계정 한도에 등록한다
from notree.platform.db import user_tx
from notree.platform.jobs import (
    ConcurrencyLimit,
    Job,
    JobNotRunning,
    Outbox,
    complete_job,
    enqueue,
    handler,
    job_tx,
    on_failure,
    run_job,
)
from notree.platform.usage import UsageLedger
from tests.conftest import login

pytestmark = pytest.mark.anyio


def fake_kiq(
    monkeypatch: pytest.MonkeyPatch, *, fail: bool = False
) -> list[tuple[int, int]]:
    """큐 전송을 가로채 보낸 인자를 모은다. compose의 워커가 테스트 작업을 가져가 상태를 바꾸지 않게 한다."""
    sent: list[tuple[int, int]] = []

    async def kiq(job_id: int, user_id: int) -> None:
        if fail:
            raise ConnectionError
        sent.append((job_id, user_id))

    monkeypatch.setattr(run_job, "kiq", kiq)
    return sent


async def delete_jobs(user_id: int) -> None:
    async with user_tx(user_id) as db:
        # RLS가 이 사용자의 작업만 지운다. outbox는 CASCADE로 함께 지워진다
        await db.execute(delete(Job))


@pytest.fixture
async def users() -> AsyncIterator[tuple[int, int]]:
    """작업이 없는 테스트 사용자 둘. 앞선 실행이 남긴 작업이 한도 계산에 끼지 않게 먼저 지운다."""
    ids = (await login("test-jobs-a"), await login("test-jobs-b"))
    for user_id in ids:
        await delete_jobs(user_id)
    yield ids
    for user_id in ids:
        await delete_jobs(user_id)


async def add_job(user_id: int, kind: str, status: str = "queued") -> Job:
    """enqueue를 거치지 않고 작업 행만 만든다."""
    async with user_tx(user_id) as db:
        job = Job(user_id=user_id, kind=kind, status=status)
        db.add(job)
    return job


async def reload(job: Job) -> Job:
    async with user_tx(job.user_id) as db:
        return await db.get_one(Job, job.id)


async def outbox_of(job: Job) -> list[Outbox]:
    async with user_tx(job.user_id) as db:
        return list(await db.scalars(select(Outbox).where(Outbox.job_id == job.id)))


async def test_enqueue_sends_after_commit(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, _ = users
    sent = fake_kiq(monkeypatch)

    async with user_tx(user_id) as db:
        job = await enqueue(db, "purge", target_id=7)
        assert sent == []  # 커밋 전에는 보내지 않는다

    assert sent == [(job.id, user_id)]  # 메시지에는 작업 ID와 user_id만 싣는다
    assert (job.status, job.target_id, job.user_started) == ("queued", 7, False)
    [outbox] = await outbox_of(job)
    assert outbox.sent_at is not None


async def test_enqueue_rollback_leaves_nothing(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, _ = users
    sent = fake_kiq(monkeypatch)

    with pytest.raises(RuntimeError):
        async with user_tx(user_id) as db:
            job_id = (await enqueue(db, "purge")).id
            raise RuntimeError

    assert sent == []
    async with user_tx(user_id) as db:
        assert await db.get(Job, job_id) is None
        assert list(await db.scalars(select(Outbox))) == []


async def test_enqueue_survives_send_failure(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, _ = users
    fake_kiq(monkeypatch, fail=True)

    async with user_tx(user_id) as db:
        job = await enqueue(db, "purge")  # 요청은 커밋됐으므로 예외가 올라오지 않는다

    assert (await reload(job)).status == "queued"
    [outbox] = await outbox_of(job)
    assert outbox.sent_at is None  # 회수 루프가 다시 보낼 행


async def test_user_started_limit(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, other_id = users
    fake_kiq(monkeypatch)
    async with user_tx(other_id) as db:  # 다른 사용자의 작업은 세지 않는다
        await enqueue(db, "grade", user_started=True)
        await enqueue(db, "grade", user_started=True)
    async with user_tx(user_id) as db:
        await enqueue(db, "final_note")  # 시스템이 만든 작업은 세지 않는다
        first = await enqueue(db, "grade", user_started=True)
        await enqueue(db, "grade", user_started=True)

    with pytest.raises(ConcurrencyLimit):
        async with user_tx(user_id) as db:
            await enqueue(db, "grade", user_started=True)

    async with user_tx(user_id) as db:  # 끝난 작업은 자리를 내준다
        await db.execute(
            update(Job).where(Job.id == first.id).values(status="succeeded")
        )
        await enqueue(db, "grade", user_started=True)


async def start_recording(user_id: int) -> None:
    """진행 중인 녹음 하나를 만든다. 앞선 실행이 남긴 과목은 먼저 지운다(RLS가 이 사용자의 것만, 강의·녹음은 CASCADE)."""
    async with user_tx(user_id) as db:
        await db.execute(text("DELETE FROM courses"))
        course_id = await db.scalar(
            text("INSERT INTO courses (user_id, name) VALUES (:u, 'c') RETURNING id"),
            {"u": user_id},
        )
        lecture_id = await db.scalar(
            text(
                "INSERT INTO lectures (user_id, course_id, title)"
                " VALUES (:u, :c, 'l') RETURNING id"
            ),
            {"u": user_id, "c": course_id},
        )
        await db.execute(
            text(
                "INSERT INTO recordings (user_id, lecture_id, status, context, started_at)"
                " VALUES (:u, :l, 'recording', '{}', now())"
            ),
            {"u": user_id, "l": lecture_id},
        )


async def test_active_recording_counts_toward_limit(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, other_id = users
    fake_kiq(monkeypatch)
    await start_recording(other_id)  # 다른 사용자의 녹음은 세지 않는다
    async with user_tx(user_id) as db:
        await db.execute(text("DELETE FROM courses"))
        await enqueue(db, "grade", user_started=True)
        await enqueue(db, "grade", user_started=True)
        await db.execute(delete(Job))

    await start_recording(user_id)
    async with user_tx(user_id) as db:
        await enqueue(db, "qa_answer", user_started=True)

    # 녹음 1 + Q&A 1로 계정당 2개가 찼다 (PER-003 5)
    with pytest.raises(ConcurrencyLimit):
        async with user_tx(user_id) as db:
            await enqueue(db, "grade", user_started=True)

    for uid in users:
        async with user_tx(uid) as db:
            await db.execute(text("DELETE FROM courses"))


async def test_concurrent_enqueues_stay_within_limit(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, _ = users
    fake_kiq(monkeypatch)

    async def try_enqueue() -> bool:
        try:
            async with user_tx(user_id) as db:
                await enqueue(db, "grade", user_started=True)
        except ConcurrencyLimit:
            return False
        return True

    assert sum(await asyncio.gather(*(try_enqueue() for _ in range(5)))) == 2


async def test_one_qa_answer_per_user(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, other_id = users
    fake_kiq(monkeypatch)
    async with user_tx(other_id) as db:
        await enqueue(db, "qa_answer", user_started=True)
    async with user_tx(user_id) as db:
        await enqueue(db, "qa_answer", user_started=True)

    with pytest.raises(ConcurrencyLimit):
        async with user_tx(user_id) as db:
            await enqueue(db, "qa_answer", user_started=True)


async def test_job_tx_saves_only_while_running(users: tuple[int, int]) -> None:
    user_id, _ = users
    job = await add_job(user_id, "purge", status="running")

    async with job_tx(job) as db:
        await db.execute(update(Job).where(Job.id == job.id).values(target_id=1))
    assert (await reload(job)).target_id == 1

    async with user_tx(user_id) as db:  # 회수 루프가 실패로 끝냈다
        await db.execute(update(Job).where(Job.id == job.id).values(status="failed"))
    with pytest.raises(JobNotRunning):
        async with job_tx(job) as db:
            await db.execute(update(Job).where(Job.id == job.id).values(target_id=2))
    assert (await reload(job)).target_id == 1


async def test_run_job_failure_calls_hook_and_releases_holds(
    users: tuple[int, int],
) -> None:
    user_id, _ = users
    failed: list[tuple[int, str | None]] = []

    @handler("grade")
    async def boom(job: Job) -> None:
        raise ValueError

    @on_failure("grade")
    async def mark_failed(db: AsyncSession, job: Job) -> None:
        # 실패 처리와 같은 트랜잭션이라 방금 바뀐 상태가 보인다
        status = await db.scalar(select(Job.status).where(Job.id == job.id))
        failed.append((job.id, status))

    job = await add_job(user_id, "grade")
    async with user_tx(user_id) as db:
        hold = UsageLedger(
            user_id=user_id,
            job_id=job.id,
            provider="openai",
            utc_date=datetime.now(UTC).date(),
            reserved_usd=Decimal("0.000001"),
        )
        db.add(hold)

    await run_job(job.id, user_id)

    done = await reload(job)
    assert (done.status, done.error_code) == ("failed", "ValueError")
    assert failed == [(job.id, "failed")]
    async with user_tx(user_id) as db:
        assert (await db.get_one(UsageLedger, hold.id)).status == "released"


async def test_failing_hook_leaves_job_for_sweeper(users: tuple[int, int]) -> None:
    user_id, _ = users

    # 처리 함수가 없는 종류. 훅 등록은 전역이라 다른 테스트가 쓰지 않는 종류를 고른다
    @on_failure("live_summary")
    async def broken_hook(db: AsyncSession, job: Job) -> None:
        raise RuntimeError

    job = await add_job(user_id, "live_summary")
    await run_job(job.id, user_id)  # 예외를 올리지 않는다

    # 실패 처리 전체가 롤백돼 running으로 남는다. 회수 루프가 다시 끝내며 훅을 다시 부른다
    done = await reload(job)
    assert (done.status, done.error_code) == ("running", None)


async def test_complete_job_commits_with_follow_up(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, _ = users
    sent = fake_kiq(monkeypatch)
    seen: list[int] = []

    @handler("purge")
    async def summarize(job: Job) -> None:
        async with job_tx(job) as db:
            await complete_job(db, job)
            await enqueue(db, "purge", target_id=job.target_id)  # 후속 작업
        # 처리 함수가 반환하기 전에 후속 작업이 시작해도 앞 작업은 이미 끝나 있다
        async with user_tx(job.user_id) as db:
            seen.extend(
                await db.scalars(
                    select(Job.id).where(
                        Job.target_id == job.target_id, Job.status == "running"
                    )
                )
            )

    async with user_tx(user_id) as db:
        job = Job(user_id=user_id, kind="purge", target_id=7)
        db.add(job)
    await run_job(job.id, user_id)

    assert seen == []
    assert (await reload(job)).status == "succeeded"  # run_job이 덮어쓰지 않는다
    assert len(sent) == 1


@pytest.mark.parametrize("kind", ["live_summary", "generate_card"])
async def test_follow_up_already_queued_keeps_save(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    user_id, _ = users
    sent = fake_kiq(monkeypatch)
    async with user_tx(user_id) as db:
        waiting = await enqueue(
            db, kind, target_id=7
        )  # 같은 대상의 후속 작업이 이미 대기 중이다
    job = await add_job(user_id, "purge", status="running")

    async with job_tx(job) as db:
        await db.execute(
            update(Job).where(Job.id == job.id).values(target_id=99)
        )  # 도메인 저장 대신
        await complete_job(db, job)
        again = await enqueue(db, kind, target_id=7)

    assert again.id == waiting.id  # 새로 넣지 않고 대기 중인 작업을 돌려준다
    done = await reload(job)
    assert (done.status, done.target_id) == ("succeeded", 99)  # 앞의 저장은 커밋됐다
    async with user_tx(user_id) as db:
        follow_ups = list(await db.scalars(select(Job.id).where(Job.kind == kind)))
        outboxes = list(await db.scalars(select(Outbox.job_id)))
    assert follow_ups == [waiting.id]
    assert outboxes == [waiting.id]  # 새 작업이 없으니 outbox도 하나다
    assert sent == [(waiting.id, user_id)]


async def test_complete_job_rolls_back_with_failed_save(
    users: tuple[int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    user_id, _ = users
    sent = fake_kiq(monkeypatch)
    job = await add_job(user_id, "purge", status="running")
    async with user_tx(user_id) as db:
        hold = UsageLedger(
            user_id=user_id,
            job_id=job.id,
            provider="openai",
            utc_date=datetime.now(UTC).date(),
            reserved_usd=Decimal("0.000001"),
        )
        db.add(hold)

    with pytest.raises(ValueError):
        async with job_tx(job) as db:
            await complete_job(db, job)
            await enqueue(db, "purge", target_id=7)
            raise ValueError  # 마지막 저장이 실패했다

    # 종료·예약 해제·후속 등록이 함께 롤백된다
    assert (await reload(job)).status == "running"
    async with user_tx(user_id) as db:
        assert (await db.get_one(UsageLedger, hold.id)).status == "held"
        assert list(await db.scalars(select(Job.id).where(Job.id != job.id))) == []
        assert list(await db.scalars(select(Outbox.id))) == []
    assert sent == []


async def test_late_failure_releases_its_holds(users: tuple[int, int]) -> None:
    user_id, _ = users
    hooked: list[int] = []

    @handler("final_note")
    async def late(job: Job) -> None:
        async with user_tx(job.user_id) as db:  # 처리 도중 회수 루프가 실패로 끝냈다
            await db.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(status="failed", error_code="stalled")
            )
            db.add(  # 그 뒤 늦게 깨어나 예약을 잡고 실패한다
                UsageLedger(
                    user_id=job.user_id,
                    job_id=job.id,
                    provider="openai",
                    utc_date=datetime.now(UTC).date(),
                    reserved_usd=Decimal("0.000001"),
                )
            )
        raise ValueError

    @on_failure("final_note")
    async def hook(db: AsyncSession, job: Job) -> None:
        hooked.append(job.id)

    job = await add_job(user_id, "final_note")
    await run_job(job.id, user_id)

    async with user_tx(user_id) as db:
        holds = await db.scalars(
            select(UsageLedger.status).where(UsageLedger.job_id == job.id)
        )
        assert list(holds) == ["released"]
    assert (await reload(job)).error_code == "stalled"
    assert hooked == []  # 훅은 회수 루프가 이미 불렀다


@pytest.mark.parametrize("saves_late", [False, True])
async def test_run_job_keeps_sweeper_failure(
    users: tuple[int, int], saves_late: bool
) -> None:
    user_id, _ = users
    hooked: list[int] = []

    @handler("purge")
    async def slow(job: Job) -> None:
        async with user_tx(job.user_id) as db:  # 처리 도중 회수 루프가 실패로 끝냈다
            await db.execute(
                update(Job)
                .where(Job.id == job.id)
                .values(status="failed", error_code="stalled")
            )
        if saves_late:
            async with job_tx(job):
                pass

    @on_failure("purge")
    async def hook(db: AsyncSession, job: Job) -> None:
        hooked.append(job.id)

    job = await add_job(user_id, "purge")
    await run_job(job.id, user_id)

    done = await reload(job)
    assert (done.status, done.error_code) == ("failed", "stalled")
    assert hooked == []  # 훅은 회수 루프가 부른다. 여기서 또 부르지 않는다
