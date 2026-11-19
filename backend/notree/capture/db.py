"""capture의 테이블 매핑과 쿼리. 다른 모듈은 테이블을 직접 읽지 않고 이 파일의 함수를 부른다."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import FetchedValue, insert, literal, select, text
from sqlalchemy.dialects.postgresql import ARRAY, TEXT
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from notree.platform.db import Base
from notree.platform.jobs import counts_toward_limit


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    name: Mapped[str]
    background: Mapped[str] = mapped_column(server_default=FetchedValue())
    terms: Mapped[list[str]] = mapped_column(ARRAY(TEXT), server_default=FetchedValue())
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=FetchedValue())


class Lecture(Base):
    __tablename__ = "lectures"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int]
    course_id: Mapped[int]
    title: Mapped[str]
    deleted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=FetchedValue())


async def list_courses(db: AsyncSession) -> Sequence[Course]:
    result = await db.scalars(
        select(Course).where(Course.deleted_at.is_(None)).order_by(Course.created_at)
    )
    return result.all()


async def create_lecture(
    db: AsyncSession, course_id: int, title: str
) -> Lecture | None:
    """자식 행은 부모에서 user_id를 복사해 만든다. 남의 과목이거나 없는 과목이면 None이다.

    FK가 단일 열이라 DB는 자식의 user_id가 부모와 같은지 확인하지 않는다 (docs/schema-mvp.md 보안).
    """
    parent = select(Course.user_id, Course.id, literal(title)).where(
        Course.id == course_id, Course.deleted_at.is_(None)
    )
    return await db.scalar(
        insert(Lecture)
        .from_select(["user_id", "course_id", "title"], parent)
        .returning(Lecture)
    )


@counts_toward_limit
async def count_active_recordings(db: AsyncSession) -> int:
    """진행 중인 녹음 수. 녹음도 사용자가 시작한 작업이라 계정 동시 실행 한도에 든다 (PER-003 5)."""
    count: int = await db.scalar(
        text("SELECT count(*) FROM recordings WHERE status IN ('recording', 'paused')")
    )
    return count
