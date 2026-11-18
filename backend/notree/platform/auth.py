"""요청을 보낸 사용자를 알아낸다. 라우터는 Depends(current_user_id)로 받는다."""

import os

from fastapi import HTTPException
from sqlalchemy import text

from notree.platform.db import engine


async def current_user_id() -> int:
    # shortcut: 모든 요청이 시드 사용자 'dev'가 된다, 구글 로그인을 붙일 때 세션 쿠키로 sessions를 조회하게 바꾼다
    if os.environ.get("NOTREE_DEV_AUTH") != "1":
        raise HTTPException(401)
    async with engine.begin() as conn:
        user_id: int = await conn.scalar(
            text("SELECT login_user('dev', 'dev@example.com')")
        )
        return user_id
