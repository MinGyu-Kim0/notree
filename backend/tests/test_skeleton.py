"""뼈대 확인. compose로 띄운 DB에 붙어서 돈다: docker compose exec api pytest"""

import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import DBAPIError

import notree.api  # noqa: F401  모든 모델을 Base.metadata에 올린다
from notree.capture.db import Course, create_lecture, list_courses
from notree.platform.db import Base, engine, user_tx
from notree.platform.jobs import Job, handler, run_job
from tests.conftest import login

pytestmark = pytest.mark.anyio


async def test_models_match_schema() -> None:
    """모델을 손으로 쓰므로 schema-mvp.sql과 어긋나면 여기서 잡는다."""
    async with engine.connect() as conn:
        for table in Base.metadata.tables.values():
            rows = await conn.scalars(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_name = :t"
                ),
                {"t": table.name},
            )
            assert set(rows) == {c.name for c in table.columns}, table.name


async def test_user_boundary() -> None:
    a, b = await login("test-a"), await login("test-b")
    async with user_tx(a) as db:
        course = Course(user_id=a, name="A의 과목")
        db.add(course)
    try:
        async with user_tx(a) as db:
            assert course.id in [c.id for c in await list_courses(db)]
            assert await create_lecture(db, course.id, "1주차") is not None
        async with user_tx(b) as db:
            assert course.id not in [c.id for c in await list_courses(db)]
            assert await create_lecture(db, course.id, "남의 과목에 강의 넣기") is None
        with pytest.raises(DBAPIError):  # 사용자를 정하지 않으면 조회가 실패한다
            async with engine.connect() as conn:
                await conn.execute(text("SELECT count(*) FROM courses"))
    finally:
        async with user_tx(a) as db:
            await db.execute(delete(Course).where(Course.id == course.id))


async def test_run_job() -> None:
    user_id = await login("test-a")
    seen: list[int | None] = []

    @handler("purge")
    async def ok(job: Job) -> None:
        seen.append(job.target_id)

    @handler("grade")
    async def boom(job: Job) -> None:
        raise ValueError("원문이 섞였을 수 있는 메시지")

    async with user_tx(user_id) as db:
        jobs = [
            Job(user_id=user_id, kind=kind, target_id=7)
            for kind in ("purge", "grade", "generate_card")
        ]
        db.add_all(jobs)  # enqueue를 쓰지 않는다. 떠 있는 워커가 먼저 가져가면 안 된다
    for job in jobs:
        await run_job(job.id, user_id)
    await run_job(jobs[0].id, user_id)  # 두 번 전달돼도 한 번만 실행한다

    async with user_tx(user_id) as db:
        done = [await db.get_one(Job, job.id, populate_existing=True) for job in jobs]
        assert [(j.status, j.error_code, j.attempt) for j in done] == [
            ("succeeded", None, 1),
            ("failed", "ValueError", 1),
            ("failed", "no_handler", 1),
        ]
        assert seen == [7]
        await db.execute(delete(Job).where(Job.id.in_([j.id for j in jobs])))
