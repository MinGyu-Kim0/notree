"""모듈 라우터 예시: 사용자를 받고, user_tx를 열고, db.py의 함수를 부른다."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from notree.capture import db as capture_db
from notree.platform.auth import current_user_id
from notree.platform.db import user_tx

router = APIRouter(prefix="/api/courses")
UserId = Annotated[int, Depends(current_user_id)]


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    background: str
    terms: list[str]


class LectureIn(BaseModel):
    title: str


class LectureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    course_id: int
    title: str


@router.get("")
async def list_courses(user_id: UserId) -> list[CourseOut]:
    async with user_tx(user_id) as db:
        return [CourseOut.model_validate(c) for c in await capture_db.list_courses(db)]


@router.post("/{course_id}/lectures", status_code=201)
async def create_lecture(
    course_id: int, body: LectureIn, user_id: UserId
) -> LectureOut:
    async with user_tx(user_id) as db:
        lecture = await capture_db.create_lecture(db, course_id, body.title)
    if lecture is None:
        raise HTTPException(404)
    return LectureOut.model_validate(lecture)
