"""회수 루프. 보내지 못한 작업 전달을 다시 보내고, 멈춘 작업을 실패로 끝낸다.

worker 프로세스 안에서 돈다. notree/worker.py가 이 파일을 import해야 시작된다.
동작과 이유는 docs/schema-mvp.md '작업 전달과 멈춘 작업'에 있다.
"""

import asyncio
import logging
from datetime import timedelta

from sqlalchemy import text
from taskiq import TaskiqEvents, TaskiqState

from notree.platform.db import engine, user_tx
from notree.platform.jobs import broker, fail_job, send_outbox

log = logging.getLogger(__name__)

# 넷 다 초기값이다. 장애 시험(docs/testing/failure-matrix.md)을 돌려 보고 조정한다
SWEEP_INTERVAL = timedelta(seconds=30)
UNSENT_AFTER = timedelta(seconds=30)  # 커밋 직후의 전송이 끝날 시간을 준다
RESEND_AFTER = timedelta(
    minutes=5
)  # 보냈는데도 이만큼 queued면 Redis에서 메시지를 잃은 것으로 본다
STALLED_QA = timedelta(minutes=3)
STALLED_BACKGROUND = timedelta(minutes=30)


async def sweep_once() -> None:
    """회수를 한 번 한다. 워커가 여럿이라 겹쳐 돌아도 된다. 전달은 받는 쪽이 중복을 거르고, 멈춘 작업은 한쪽만 끝낸다."""
    # 여러 사용자의 행을 훑으므로 user_tx가 아니라 SECURITY DEFINER 함수로 읽는다 (ADR-0010)
    async with engine.begin() as conn:
        unsent = (
            await conn.execute(
                text(
                    "SELECT outbox_id, job_id, user_id FROM unsent_outbox(:older, :resend)"
                ),
                {"older": UNSENT_AFTER, "resend": RESEND_AFTER},
            )
        ).all()
    for outbox_id, job_id, user_id in unsent:
        await send_outbox(outbox_id, job_id, user_id)

    async with engine.begin() as conn:
        stalled = (
            await conn.execute(
                text("SELECT job_id, user_id FROM stalled_jobs(:qa, :background)"),
                {"qa": STALLED_QA, "background": STALLED_BACKGROUND},
            )
        ).all()
    for job_id, user_id in stalled:
        # 작업마다 따로 끝낸다. 한 작업의 훅이 실패해도 나머지는 끝내고, 실패한 작업은 다음 회수 때 다시 한다
        try:
            async with user_tx(user_id) as db:
                await fail_job(db, job_id, "stalled")
        except Exception as e:  # noqa: BLE001  훅의 예외 메시지에는 원문이 섞일 수 있어 ID와 예외 종류만 남긴다
            log.error("stalled job %s not failed: %s", job_id, type(e).__name__)


async def _sweep_forever() -> None:
    while True:
        try:
            await sweep_once()
        except Exception:
            # DB가 잠깐 끊겨도 루프는 살아 있어야 한다. 여기까지 오는 예외는 회수 함수 호출의 것이라 원문이 없다
            log.exception("sweep failed")
        await asyncio.sleep(SWEEP_INTERVAL.total_seconds())


@broker.on_event(TaskiqEvents.WORKER_STARTUP)
async def _start(state: TaskiqState) -> None:
    state.sweeper = asyncio.create_task(_sweep_forever())


@broker.on_event(TaskiqEvents.WORKER_SHUTDOWN)
async def _stop(state: TaskiqState) -> None:
    state.sweeper.cancel()
