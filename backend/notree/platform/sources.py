"""출처 검증 (ADR-0007). AI가 낸 근거 가운데 그 작업의 입력 안에 있는 것만 남긴다."""

from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID


def verify_sources(
    sources: list[dict[str, Any]],  # Any: AI 출력이라 값의 타입을 믿을 수 없다
    *,
    segment_ids: Collection[int] = (),
    block_revisions: Mapping[UUID, int] = {},
    urls: Mapping[str, datetime] = {},
) -> list[dict[str, Any]]:  # Any: 저장 형식의 값이 int 또는 str이다
    """통과한 근거를 저장 형식으로 돌려준다. 통과하지 못한 근거는 예외 없이 버린다.

    segment_ids는 넣어 준 전사 구간, block_revisions는 넣어 준 블록과 그때의 판 번호,
    urls는 웹 검색 도구 응답의 인용 목록과 조회 시각이다.
    블록의 판 번호와 웹 근거의 조회 시각(SFR-010 1)은 AI 출력이 아니라 여기서 붙인다.
    """
    revisions = {
        str(block_id): revision for block_id, revision in block_revisions.items()
    }
    verified: list[dict[str, Any]] = []  # Any: 위 반환형과 같다
    for source in sources:
        match source:
            # type(...) is int: True도 int라서 `True in {1}`이 통과한다
            case {"segment_id": segment_id} if (
                type(segment_id) is int and segment_id in segment_ids
            ):
                verified.append({"segment_id": segment_id})
            case {"block_id": str(block_id)} if block_id in revisions:
                verified.append({"block_id": block_id, "revision": revisions[block_id]})
            case {"url": str(url)} if url in urls:
                verified.append({"url": url, "fetched_at": urls[url].isoformat()})
    return verified
