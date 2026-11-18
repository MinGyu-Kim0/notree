"""DB 세션. 사용자 데이터는 모두 user_tx 안에서 읽고 쓴다."""

import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

engine = create_async_engine(
    os.environ.get(
        "DATABASE_URL", "postgresql+psycopg://notree_app:dev@127.0.0.1:54320/notree"
    )
)
_Session = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    """모델은 매핑만 한다. 테이블·제약·RLS의 원본은 docs/schema-mvp.sql이다."""


@asynccontextmanager
async def user_tx(user_id: int) -> AsyncIterator[AsyncSession]:
    """한 사용자의 트랜잭션. RLS가 이 사용자의 행만 보여 준다. 예외가 나면 롤백한다.

    AI 호출처럼 오래 걸리는 일은 이 블록 밖에서 한다. 30초 동안 쿼리가 없으면 DB가 연결을 끊는다.
    """
    async with _Session() as db:
        async with db.begin():
            await db.execute(
                text("SELECT set_config('app.user_id', :id, true)"),
                {"id": str(user_id)},
            )
            db.info["user_id"] = user_id
            yield db
        for callback in db.info.pop("after_commit", []):
            await callback()


def after_commit(db: AsyncSession, callback: Callable[[], Awaitable[object]]) -> None:
    """커밋된 뒤에 할 일을 등록한다. 롤백되면 실행하지 않는다."""
    db.info.setdefault("after_commit", []).append(callback)
