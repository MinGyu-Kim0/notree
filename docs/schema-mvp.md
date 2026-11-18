# Notree MVP 스키마

- 작성일: 2026-11-18
- SQL: [schema-mvp.sql](schema-mvp.sql)(테이블·FK·인덱스·한글 논리명), [schema-mvp-security.sql](schema-mvp-security.sql)(역할·RLS·권한)
- 바탕: 23개 테이블 안(v2, 지금은 레포에 없음)에서 핵심 흐름만 남겨 18개로 줄였다. 녹음·전사 → 노트 → Q&A로 노트 보완 → 이해 상태에 맞춘 복습.
- 논리명은 `COMMENT ON TABLE/COLUMN`에 있다. ERD 도구의 논리 뷰가 이 값을 쓴다.
- ERDCloud: [schema-mvp.erdcloud.json](schema-mvp.erdcloud.json)을 스냅샷 가져오기로 넣는다. 논리명은 한글, 물리명은 SQL 이름이다.

## ERDCloud 스냅샷 다시 만들기

SQL을 바꾸면 스냅샷도 다시 만든다. 스크립트가 DB 카탈로그에서 테이블·열·FK·COMMENT를 읽는다. 화면 배치(영역별 열)는 [scripts/erdcloud_snapshot.py](../scripts/erdcloud_snapshot.py)의 `COLUMNS`에서 바꾼다.

```bash
docker run -d --rm --name notree-mvp -e POSTGRES_PASSWORD=x postgres:17.6
docker exec -i notree-mvp psql -U postgres -q < docs/schema-mvp.sql
docker exec -i notree-mvp psql -U postgres -Atq -c "$(python3 scripts/erdcloud_snapshot.py --query)" | python3 scripts/erdcloud_snapshot.py > docs/schema-mvp.erdcloud.json
docker stop notree-mvp
```

- ID는 테이블·열 이름에서 만들어서, 다시 만들어도 바뀐 테이블만 diff에 나온다.
- 관계선은 단일 열 FK만 그린다. 관계 종류는 모두 `ZERO_OR_ONE_OR_MANY`(샘플에서 확인한 값)다.
- `CHECK`·`UNIQUE`·인덱스는 스냅샷에 담기지 않는다. 원본은 SQL이다.

## 테이블

| 영역 | 논리명 | 물리명 | 한 줄 설명 |
|---|---|---|---|
| 계정 | 사용자 | `users` | 구글 계정, 동의 시각, 하루 학습 시간, 탈퇴 상태 |
| | 로그인 세션 | `sessions` | 쿠키 해시와 만료·철회 |
| 강의 기록 | 과목 | `courses` | 과목명과 맥락(배경 설명·전문용어) |
| | 강의 | `lectures` | 과목에 속한 강의 |
| | 녹음 세션 | `recordings` | 강의 하나에 여럿. 시작 시점 맥락을 `context`에 고정 |
| | 전사 구간 | `segments` | STT 원문과 사용자 정정 |
| 노트 | 노트 | `notes` | 강의 노트(강의당 1개)·과목 노트(과목당 1개), 생성 상태 |
| | 노트 블록 | `note_blocks` | 블록의 현재 내용, 순서와 깊이, 근거, 판 번호. ID는 편집기가 만드는 UUIDv7(ADR-0013) |
| | 블록 이력 | `block_revisions` | 블록이 바뀔 때마다 한 행. 이력 조회·되돌리기 |
| 질의응답 | 대화 | `conversations` | 과목별 대화 |
| | 대화 메시지 | `messages` | 질문 원문, 완료된 답변, Q&A 단계별 결과(답변·노트 반영·학습 상태 갱신) |
| | 노트 변경안 | `note_changes` | Q&A가 제안한 노트 변경과 처리 상태(확인 필요·반영·거절·되돌림·보류) |
| 학습자 | 개념 | `concepts` | 과목별 개념과 이해 상태 |
| | 관찰 | `observations` | 이해 상태의 근거. 복습 답안 또는 Q&A에서 나온다 |
| 복습 | 복습 카드 | `review_cards` | 문제 하나와 FSRS 일정 |
| | 제출 답안 | `attempts` | 답안과 평가 결과 |
| 운영 | 작업 | `jobs` | 백그라운드 작업 상태. Redis 메시지에는 작업 ID와 `user_id`만 |
| | 비용 장부 | `usage_ledger` | AI 비용 예약·정산 |

## v2에서 뺀 것

| v2에 있던 것 | MVP에서 | 나중에 필요해지는 때 |
|---|---|---|
| `trash_batches`, 모든 테이블의 `trash_id` | 과목·강의·노트·대화의 `deleted_at`만. 자식은 부모를 거쳐 조회 | 삭제 범위 확인 화면, 묶음 단위 복원(SFR-048) |
| `context_versions` | `courses`에 현재 맥락, `recordings.context`에 고정본 | 녹음 중 용어 즉시 적용(SFR-046 3) |
| `note_versions` | 블록별 이력(`block_revisions`)만. 깊이(ADR-0020)는 `note_blocks.depth`에 둔다 | 노트 전체를 특정 판으로 복원(SFR-010 5) |
| `search_docs`(pgvector + pg_bigm) | 없음. Q&A는 과목 노트를 통째로 맥락에 넣는다 | 노트가 맥락 창을 넘을 때, 노트 검색(SFR-047) |
| `review_units` + `review_items` + `gradings` | `review_cards` + `attempts` | 문제 재생성 이력, 재평가 이력(DAR-004 4) |
| 전사 수정 제안, 정지 구간, 답안 초안, 작업 단계 기록(`job_stages`) | 없음 | SFR-058, DAR-001 5, SFR-052 4, QUR-007 |

## LangGraph

LangGraph 체크포인터를 쓰지 않으므로 LangGraph 자체 테이블(`checkpoints` 등)은 만들지 않는다(ADR-0009).

- Q&A 그래프는 메모리에서만 돌고, 결과만 `messages`·`note_changes`·`observations`에 저장한다.
- Q&A는 ADR-0022대로 `qa_answer` 하나가 답변 → 반영 → 관찰 단계를 하고, 완료 표시는 `messages.answer_status`·`reflect_status`·`learner_status`다.
- 과목 노트 업데이트는 모든 단계의 결과를 마지막에 한 트랜잭션으로 반영한다. 중간에 실패하면 처음부터 다시 돌린다. AI 호출은 반복되지만 같은 변경이 두 번 반영되지는 않는다.
- 실패한 단계부터 재개해야 하면(SFR-043 2), ADR-0009대로 `jobs.completed_stages text[]`를 추가하고 단계마다 결과와 함께 커밋한다.

## 보안

- 모든 사용자 테이블에 `user_id` + RLS(`sessions` 제외). 자식 테이블의 `user_id`는 관계가 아니라 RLS용 복사본이라 `users`로 FK를 걸지 않는다. 소유는 부모 FK 체인(과목 → 사용자)으로 이어진다.
- `jobs`도 RLS를 받는다. 워커는 사용자를 모르면 작업 행을 읽지 못하므로, 작업 메시지에 작업 ID와 `user_id`를 함께 싣고 워커가 그 값으로 `SET LOCAL app.user_id`를 한다. 여러 사용자의 대기 작업을 훑는 회수 루프는 아직 없다. 만들 때 `SECURITY DEFINER` 함수를 추가한다(ADR-0010).
- 앱 계정은 `users`·`block_revisions`·`observations`·`usage_ledger`를 지울 수 없고, `block_revisions`·`observations`는 고칠 수도 없다. 영구 삭제는 cron(`notree_admin`)만 한다.
- FK는 단일 열이라 자식의 `user_id`가 부모와 같은지 DB가 확인하지 않는다. 자식은 부모를 RLS로 걸러 읽는 `INSERT ... SELECT ... FROM <부모> WHERE id = $1`로 만든다. 남의 부모 ID면 0행이 들어가고, `user_id`도 부모에서 복사된다.
