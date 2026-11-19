# `capture`를 `notebook`·`learner` 아래 층으로 내려, 모든 모듈이 과목·강의·전사를 읽을 수 있게 한다

과목·강의·전사(`courses`, `lectures`, `segments`)는 `capture`의 데이터인데 모든 모듈이 읽어야 한다. 이전 계층은 위에서 아래로 `capture | tutor | review | account` / `notebook | learner` / `platform`이어서 `capture`가 최상층이었고, 어느 모듈도 `capture`를 부를 수 없었다. 그래서 세 가지가 막혔다. 첫째, `tutor`가 MVP Q&A 맥락에 넣는 '녹음 중 강의의 확정 전사'를 읽을 길이 없었다. 둘째, 강의 최종 노트는 전사 전체가 필요한데 `notebook`이 전사를 읽을 수 없어 처리 함수를 `notebook`에 둘 수 없었다. 셋째, `notes`·`conversations`·`concepts`의 부모가 `courses`·`lectures`라서, 자식 행을 부모에서 `user_id`를 복사해 만든다는 README 규칙을 `notebook`·`tutor`·`learner`가 지킬 수 없었다. 대안은 둘이었다. `tutor → capture` 화살표만 더하면 첫째만 풀리고 둘째와 셋째가 남는다. `courses`·`lectures`를 별도 모듈로 떼면 모듈이 하나 늘고 담당이 갈린다. 그래서 `capture`를 `notebook`·`learner` 아래로 내린다. 계층은 위에서 아래로 `tutor | review | account` / `notebook | learner` / `capture` / `platform`이다.

## Consequences

- 위층은 아래층의 공개 함수를 부를 수 있고, 바로 아래층이 아니어도 된다. 같은 층끼리, 그리고 아래에서 위로는 부르지 않고 작업 등록(`enqueue`)으로 알린다. `backend/pyproject.toml`의 import-linter 계약과 `docs/architecture.md` 3절 그림이 이 계층과 같은 방향만 허용한다.
- `capture`가 `notebook`을 부르던 호출이 없어진다. 녹음 세션이 끝나면 `capture`가 `enqueue("final_note", target_id=강의 ID)`로 알린다. `final_note` 처리 함수는 `notebook`에 있고, 전사를 `capture`의 공개 함수로 읽는다.
- `tutor`는 녹음 중 강의의 확정 전사를 `capture`의 공개 함수로 읽는다.
- `notebook`·`tutor`·`learner`는 `capture`의 공개 함수로 부모(`courses`, `lectures`)를 읽어 자식 행의 `user_id`를 부모에서 복사한다.
- `account`는 계정 용량을 세려고 `capture`를 읽을 수 있다.
- `capture`는 `platform`만 import할 수 있다. 노트·대화·개념을 읽어야 하는 처리는 `capture`에 두지 않는다.
