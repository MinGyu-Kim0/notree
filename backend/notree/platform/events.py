"""화면으로 보내는 이벤트 (ADR-0005). 사용자별 Redis Stream에 쌓고 GET /events가 SSE로 내보낸다."""

import json
import os
from collections.abc import AsyncGenerator, Mapping
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from notree.platform.auth import current_user_id

router = APIRouter()
# 이벤트가 없을 때 주석 줄을 보내는 간격. 조용한 연결을 중간 장비가 끊지 않게 한다
KEEPALIVE_MS = 15_000
MAX_EVENTS = 1000  # 사용자별로 남기는 이벤트 수(약). 넘으면 오래된 것부터 잘린다
redis = Redis.from_url(
    os.environ.get("REDIS_URL", "redis://127.0.0.1:6379"),
    decode_responses=True,
    # XREAD가 KEEPALIVE_MS 동안 기다린다. 읽기 timeout(redis-py 기본 5초)이 그보다 짧으면 기다리다 끊긴다
    socket_timeout=KEEPALIVE_MS / 1000 + 5,
)
# decode_responses=True일 때의 응답 모양. redis-py의 반환형은 bytes | str 합집합이라 cast로 좁힌다
_Entries = list[tuple[str, dict[str, str]]]


async def publish(user_id: int, event: str, data: Mapping[str, Any]) -> str:
    """사용자의 화면으로 이벤트를 보내고 Stream ID를 돌려준다. 워커와 API가 진행·토큰·완료를 알릴 때 부른다.

    질문 원문은 data에 싣지 않는다(부르는 쪽이 지킨다). data에는 답변 토큰이 실리므로 로그에 남기지 않는다.
    """
    # shortcut: 실행 시도 번호를 붙이지 않고 완료·실패·취소도 outbox 없이 바로 보낸다, ADR-0018·0019의 장치를 넣을 때 고친다
    stream_id = await redis.xadd(
        f"events:{user_id}",
        {"event": event, "data": json.dumps(dict(data))},
        maxlen=MAX_EVENTS,  # approximate가 기본값이라 MAX_EVENTS보다 적게 남지는 않는다
    )
    return cast(str, stream_id)


async def stream(user_id: int, last_event_id: str | None) -> AsyncGenerator[str, None]:
    """SSE 형식 문자열을 끝없이 낸다. last_event_id가 있으면 그 뒤부터, 없으면 지금부터 보낸다.

    그 뒤 이벤트가 잘려 나갔을 수 있으면 먼저 reload(전체 상태 다시 불러오기 신호)를 내고 지금부터 보낸다.
    """
    key = f"events:{user_id}"
    newest = cast(_Entries, await redis.xrevrange(key, count=1))
    cursor = newest[0][0] if newest else "0-0"
    if last_event_id:
        # 마지막으로 받은 이벤트가 남아 있으면 그 뒤는 잘리지 않았다(Stream은 오래된 쪽부터 잘린다).
        # Last-Event-ID는 화면이 보낸 값이라 형식이 틀릴 수 있고, 그때도 reload로 답한다.
        try:
            seen = cast(
                _Entries,
                await redis.xrange(key, last_event_id, last_event_id, count=1),
            )
        except ResponseError:
            seen = []
        if seen:
            cursor = seen[0][0]
        else:
            yield "event: reload\ndata: {}\n\n"
    else:
        # 이벤트를 하나도 받기 전에 끊긴 화면은 Last-Event-ID 없이 다시 붙어 그사이 이벤트를 놓친다.
        # data 없는 id 줄은 이벤트로 전달되지 않고 화면의 마지막 이벤트 ID만 바꾼다
        yield f"id: {cursor}\n\n"
    # shortcut: SSE 연결 하나가 XREAD로 Redis 연결 하나를 잡는다, 동시 접속이 Redis 연결 수 한도에 가까워지면 프로세스당 리더 하나로 합친다
    while True:
        batches = cast(
            list[tuple[str, _Entries]],
            await redis.xread({key: cursor}, block=KEEPALIVE_MS),
        )
        if not batches:
            yield ": keepalive\n\n"
            continue
        entries = batches[0][1]
        # 느린 화면이 읽지 않는 사이 cursor 뒤가 잘렸을 수 있다. 잘렸다면 남은 것이 한꺼번에 MAX_EVENTS건 넘게 온다.
        # 그때 마지막으로 보낸 이벤트가 Stream에 없으면 그 뒤를 놓쳤을 수 있으니 reload로 알리고 지금부터 보낸다
        if len(entries) >= MAX_EVENTS and not await redis.xrange(
            key, cursor, cursor, count=1
        ):
            cursor = entries[-1][0]
            yield "event: reload\ndata: {}\n\n"
            continue
        for cursor, fields in entries:
            yield f"id: {cursor}\nevent: {fields['event']}\ndata: {fields['data']}\n\n"


@router.get("/events")
async def events(
    user_id: Annotated[int, Depends(current_user_id)],
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    return StreamingResponse(
        stream(user_id, last_event_id), media_type="text/event-stream"
    )
