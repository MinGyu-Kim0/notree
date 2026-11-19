"""OpenAI 클라이언트. 모델 호출은 모두 여기서 받은 클라이언트로 한다 (ADR-0009, ADR-0017)."""

from openai import AsyncOpenAI


def ai_client(*, timeout: float, qa_answer: bool = False) -> AsyncOpenAI:
    """재시도는 SDK에만 맡긴다: 배경 작업 2회, `qa_answer` 작업의 모든 단계 1회 (ADR-0017, ADR-0022).

    timeout(초)에 기본값이 없는 건 SDK 기본값이 10분이라서다. 작업 마감까지 남은 시간 안에서 부르는 쪽이 정한다.
    비용 예약과 정산은 부르는 쪽이 platform/usage.py로 한다.
    """
    # shortcut: 부를 때마다 연결 풀을 새로 만든다, 호출 지연이 문제가 되면 클라이언트 하나를 두고 with_options로 바꾼다
    return AsyncOpenAI(timeout=timeout, max_retries=1 if qa_answer else 2)
