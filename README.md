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
- AI 호출을 쓰려면 `OPENAI_API_KEY`를 셸 환경 변수나 `deploy/.env`에 둔다. 없어도 뜨고, AI 호출만 실패한다.
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

다른 모듈은 위층에서 아래층으로만 부른다: `tutor`·`review`·`account` → `notebook`·`learner` → `capture` → `platform`. 같은 층끼리나 아래에서 위로 알릴 일은 작업으로 등록한다.

- **`db.py`**: 그 모듈 테이블의 SQLAlchemy 모델과 쿼리 함수. 모델은 매핑만 한다. 테이블의 원본은 `docs/schema-mvp.sql`이고, 둘이 어긋나면 테스트가 잡는다. 다른 모듈의 테이블은 그 모듈 `db.py`의 함수로만 읽는다.
- **`api.py`**: 라우터. `Depends(current_user_id)`로 사용자를 받고 `async with user_tx(user_id) as db:` 안에서 `db.py`의 함수를 부른다. 라우터는 [backend/notree/api.py](backend/notree/api.py)에 한 줄 더한다.
- **작업**: `user_tx`나 `job_tx` 안에서 `await enqueue(db, "final_note", target_id=...)`로 등록하고, `@handler("final_note")`를 붙인 함수가 워커에서 처리한다. 처리 함수는 결과를 `async with job_tx(job) as db:` 안에서 저장한다. 작업이 실패했을 때 도메인 상태(`notes.status` 등)를 실패로 바꾸는 일은 `@on_failure("final_note")`를 붙인 함수 `hook(db, job)`에 둔다. 훅은 `jobs`를 `failed`로 바꾸는 트랜잭션 안에서 불리므로 그 `db`로 쓰고, 새 트랜잭션을 열지 않는다. 두 함수가 든 파일을 [backend/notree/worker.py](backend/notree/worker.py)에서 import한다. 사용자가 눌러 시작하는 작업은 `enqueue(..., user_started=True)`로 등록하고, `ConcurrencyLimit`이 나면 429로 돌려준다. 녹음 시작도 계정 한도에 들므로, 녹음을 만드는 트랜잭션에서 `user_started_count(db)`가 `MAX_USER_STARTED` 이상이면 429로 돌려준다.

꼭 지킬 것:

- 사용자 데이터는 `user_tx` 안에서만 읽고 쓴다. 밖에서 조회하면 RLS가 오류를 낸다.
- AI 호출처럼 오래 걸리는 일은 `user_tx` 밖에서 한다. 트랜잭션이 30초 동안 쉬면 DB가 연결을 끊는다.
- AI 호출은 `ai_client(timeout=..., qa_answer=...)`가 준 클라이언트로 한다. 호출 전에 `usage.reserve`로 비용을 예약하고 호출 뒤에 `usage.settle`로 정산한다. 예약과 정산은 `user_tx` 안에서, 호출은 그 사이 트랜잭션 밖에서 한다.
- AI 출력의 근거는 `verify_sources`를 거친 것만 저장한다.
- 화면에 알릴 일은 `events.publish(user_id, event, data)`로 보낸다. 화면은 `GET /events`(SSE)로 받고, 다시 붙을 때 `Last-Event-ID` 뒤의 이벤트가 이미 잘렸으면 `reload` 이벤트를 받는다.
- 자식 행은 부모에서 `user_id`를 복사해 만든다(`capture/db.py`의 `create_lecture`). DB는 자식의 `user_id`가 부모와 같은지 확인하지 않는다. 부모가 다른 모듈의 테이블이면 그 모듈의 조회 함수로 부모를 읽고, 읽은 행의 `user_id`를 넣는다. 행이 없으면 남의 것이거나 없는 것이다.
- 블록 ID는 UUIDv7이다. 그 밖의 ID는 DB가 만든다.
- 외부 서비스 호출, 프롬프트, FSRS·이해 상태 계산 같은 로직은 행이 아니라 값을 받는 함수로 쓴다. 스키마가 바뀌어도 그대로 쓸 수 있다.

## 아직 없는 것

프론트엔드, 구글 로그인, 녹음 WebSocket(`realtime`), `cron`. 코드에서 `shortcut:` 주석을 찾으면 알고 건너뛴 곳이 나온다.

작업 인계와 작업 단위 자동 재시도는 MVP에서 하지 않는다. 멈춘 작업을 다른 워커가 이어받으려면 늦은 저장을 막을 실행 시도 번호(ADR-0018)가 있어야 해서다. 대신 회수 루프가 멈춘 작업을 실패로 끝내고 사용자가 다시 시도한다([docs/schema-mvp.md](docs/schema-mvp.md) '작업 전달과 멈춘 작업'). 외부 호출의 재시도는 OpenAI SDK가 한다.

