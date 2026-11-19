"""출처 검증: 그 작업의 입력에 있는 근거만 통과한다 (ADR-0007, QUR-001)."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from notree.platform.sources import verify_sources

BLOCK = UUID("01937b6e-0000-7000-8000-000000000001")
OTHER_BLOCK = UUID("01937b6e-0000-7000-8000-000000000002")
CITED = "https://example.com/cited"
FETCHED = datetime(2026, 11, 19, 3, 0, tzinfo=UTC)


def verify(sources: list[Any]) -> list[dict[str, Any]]:  # Any: AI 출력을 흉내 낸다
    return verify_sources(
        sources, segment_ids={1, 2}, block_revisions={BLOCK: 3}, urls={CITED: FETCHED}
    )


def test_sources_in_input_pass_in_storage_format() -> None:
    assert verify([{"segment_id": 2}, {"block_id": str(BLOCK)}, {"url": CITED}]) == [
        {"segment_id": 2},
        {"block_id": str(BLOCK), "revision": 3},
        {"url": CITED, "fetched_at": "2026-11-19T03:00:00+00:00"},
    ]


def test_block_revision_comes_from_input_not_ai_output() -> None:
    assert verify([{"block_id": str(BLOCK), "revision": 99}]) == [
        {"block_id": str(BLOCK), "revision": 3}
    ]


def test_sources_outside_input_are_dropped() -> None:
    assert (
        verify(
            [
                {"segment_id": 999},
                {"block_id": str(OTHER_BLOCK)},
                {"url": "https://example.com/only-in-answer-text"},
            ]
        )
        == []
    )


def test_malformed_sources_are_dropped_without_error() -> None:
    assert (
        verify(
            [
                {"segment_id": "1"},
                {"segment_id": True},
                {"segment_id": [1]},
                {"block_id": 3},
                {"block_id": "uuid가 아님"},
                {"url": None},
                {"lecture_id": 1},
                {},
                "segment_id",
                None,
            ]
        )
        == []
    )


def test_nothing_passes_when_job_had_no_inputs() -> None:
    assert verify_sources([{"segment_id": 1}, {"url": CITED}]) == []


def test_fetched_at_comes_from_input_not_ai_output() -> None:
    assert verify([{"url": CITED, "fetched_at": "1999-01-01T00:00:00+00:00"}]) == [
        {"url": CITED, "fetched_at": "2026-11-19T03:00:00+00:00"}
    ]
