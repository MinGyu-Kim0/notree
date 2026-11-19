"""OpenAI 클라이언트: 재시도 횟수와 timeout (ADR-0017)."""

import pytest

from notree.platform.ai import ai_client


def test_retries_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    background = ai_client(timeout=120)
    qa_answer = ai_client(timeout=30, qa_answer=True)
    assert (background.max_retries, background.timeout) == (2, 120)
    assert (qa_answer.max_retries, qa_answer.timeout) == (1, 30)
