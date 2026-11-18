# Notree

강의를 녹음·전사해 노트로 만들고, 질의응답으로 노트를 보완하며, 이해 상태에 맞춰 복습을 내는 개인 학습 서비스. 문서 지도와 팀 공통 규칙은 [AGENTS.md](AGENTS.md)에 있다.

지금 코드는 프로토타입 뼈대다. 각 기능이 한 바퀴 도는 것까지가 목표이고, 데이터는 버린다.

## 실행

Docker만 있으면 된다.

```bash
docker compose -f deploy/compose.yaml up --build
```

- API: http://127.0.0.1:8000 (문서는 `/docs`). 코드를 고치면 `api`와 `worker`가 알아서 다시 뜬다.
- 로그인은 아직 없다. 모든 요청이 시드 사용자 `dev`로 처리된다.
- DB에는 강의 하나가 끝난 상태가 들어 있다: 과목, 강의, 전사 구간, 강의 노트와 과목 노트, 개념, 복습 카드 ([deploy/seed.sql](deploy/seed.sql)).
- DB를 직접 볼 때: `docker compose -f deploy/compose.yaml exec postgres psql -U postgres notree`. 도구로 붙을 때는 `127.0.0.1:54320`, 계정 `postgres` / `dev`.

## 스키마를 바꿀 때

마이그레이션 도구가 없다. [docs/schema-mvp.sql](docs/schema-mvp.sql)(과 필요하면 시드)을 고치고 DB를 처음부터 다시 만든다. 보안 SQL이 테이블 목록을 읽어 RLS와 권한을 붙이므로, 새 테이블도 이렇게 해야 RLS를 받는다.

```bash
docker compose -f deploy/compose.yaml down -v
```

```bash
docker compose -f deploy/compose.yaml up
```

## 검사

작업을 끝내기 전에 돌린다. 포맷, 린트, 타입, 모듈 의존 방향, 테스트를 차례로 본다. [uv](https://docs.astral.sh/uv/)가 필요하고, 테스트가 DB에 붙으므로 위 명령으로 띄워 둔 상태여야 한다.

```bash
scripts/check.sh
```

uv 없이 테스트만 돌릴 때:

```bash
docker compose -f deploy/compose.yaml exec api pytest
```

## 모듈에 코드 넣기

모듈은 `backend/notree/<모듈>`이고 담당과 의존 방향은 [docs/architecture.md](docs/architecture.md) 3절에 있다. `lint-imports`가 의존 방향을 검사한다. [backend/notree/capture](backend/notree/capture)가 예시다.

- **`db.py`**: 그 모듈 테이블의 SQLAlchemy 모델과 쿼리 함수. 모델은 매핑만 한다. 테이블의 원본은 `docs/schema-mvp.sql`이고, 둘이 어긋나면 테스트가 잡는다. 다른 모듈의 테이블은 그 모듈 `db.py`의 함수로만 읽는다.
- **`api.py`**: 라우터. `Depends(current_user_id)`로 사용자를 받고 `async with user_tx(user_id) as db:` 안에서 `db.py`의 함수를 부른다. 라우터는 [backend/notree/api.py](backend/notree/api.py)에 한 줄 더한다.
- **작업**: 요청 안에서 `await enqueue(db, "final_note", target_id=...)`로 등록하고, `@handler("final_note")`를 붙인 함수가 워커에서 처리한다. 그 함수가 든 파일을 [backend/notree/worker.py](backend/notree/worker.py)에서 import한다.

꼭 지킬 것:

- 사용자 데이터는 `user_tx` 안에서만 읽고 쓴다. 밖에서 조회하면 RLS가 오류를 낸다.
- AI 호출처럼 오래 걸리는 일은 `user_tx` 밖에서 한다. 트랜잭션이 30초 동안 쉬면 DB가 연결을 끊는다.
- 자식 행은 부모에서 `user_id`를 복사해 만든다(`capture/db.py`의 `create_lecture`). DB는 자식의 `user_id`가 부모와 같은지 확인하지 않는다.
- 블록 ID는 UUIDv7이다. 그 밖의 ID는 DB가 만든다.
- 외부 서비스 호출, 프롬프트, FSRS·이해 상태 계산 같은 로직은 행이 아니라 값을 받는 함수로 쓴다. 스키마가 바뀌어도 그대로 쓸 수 있다.

## 아직 없는 것

프론트엔드, 구글 로그인, 녹음 WebSocket(`realtime`), `cron`, SSE, 작업 재시도와 회수. 코드에서 `shortcut:` 주석을 찾으면 알고 건너뛴 곳이 나온다.
