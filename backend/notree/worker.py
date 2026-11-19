"""worker 컨테이너 진입점: taskiq worker notree.worker:broker

@handler를 쓴 모듈을 여기서 import해야 워커가 그 작업을 처리한다.
예: import notree.notebook.jobs  # noqa: F401
"""

import notree.platform.sweeper  # noqa: F401  워커가 뜰 때 회수 루프를 시작한다
from notree.platform.jobs import broker

__all__ = ["broker"]
