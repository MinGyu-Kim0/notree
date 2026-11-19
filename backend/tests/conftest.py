"""테스트 공통 준비. compose로 띄운 DB에 붙어서 돈다: docker compose exec api pytest"""

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text

from notree.platform import events
from notree.platform.db import engine
from notree.platform.jobs import broker


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
async def _close_connections(anyio_backend: str) -> AsyncIterator[None]:
    yield
    # 테스트마다 이벤트 루프가 달라서 DB·큐·이벤트 연결을 다음 테스트로 넘기지 않는다
    await engine.dispose()
    await broker.shutdown()
    await events.redis.aclose()


async def login(sub: str) -> int:
    """테스트 사용자를 만들거나 찾아 ID를 돌려준다."""
    async with engine.begin() as conn:
        user_id: int = await conn.scalar(
            text("SELECT login_user(:sub, :email)"), {"sub": sub, "email": sub}
        )
        return user_id
