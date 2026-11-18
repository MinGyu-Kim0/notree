# Notree DB 스키마 설계

- 기준: 요구사항 정의서 v0.4.3, [architecture.md](architecture.md), ADR-0001~0008
- 작성일: 2026-11-17
- 상태: 9장 결정 항목 D1~D9 확정. 되돌리기 어려운 결정은 ADR-0009~0016에 있다.
- 2026-11-17에 이 설계를 SQL로 옮겨 PostgreSQL 17 + pgvector 0.8.0 + pg_bigm 1.2에 적용하고 사용자 경계·휴지통·바꾸지 않는 기록을 점검했다(그때의 SQL은 남기지 않았다). 그때 확인한 동작은 1.4에 반영했다.
- 용어는 [GLOSSARY.md](../GLOSSARY.md)를 따른다. 테이블 이름은 영어, 설명은 용어집 용어로 쓴다.

## 1. 공통 규칙

### 1.1 대상

- PostgreSQL 17 이상, 확장 `pg_bigm`(키워드 검색)과 `vector`(pgvector, 의미 검색, [ADR-0016](adr/0016-pgvector-with-bigm.md)). `ON DELETE SET NULL (열)` 문법 때문에 15 이상이 필요하다. 쓰려는 버전을 두 확장이 지원하는지 확인한다.
- 마이그레이션은 확장 → 배포 → 정리 순서로 적용한다(architecture 7장). 그래서 ENUM 대신 `text + CHECK`를 쓴다. CHECK는 값 추가가 쉽다.

### 1.2 모든 사용자 테이블에 붙는 열

아래 DDL에서 `-- 공통`이라고 적은 자리에 다음이 들어간다. 반복을 줄이려고 생략한다.

```sql
id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
user_id    bigint NOT NULL,
created_at timestamptz NOT NULL DEFAULT now(),
UNIQUE (user_id, id)   -- 자식이 (user_id, parent_id)로 참조한다
```

- **ID**: `bigint` identity. 예외는 `blocks.id`(uuid, 9장 D1).
- **시각**: 전부 `timestamptz`. 표시만 KST로 한다(SFR-037).
- **금액**: `numeric(12,6)`. AI·STT 호출 한 건은 1센트보다 작다.
- **문자열**: `text`. 길이 제한은 CHECK로 건다.

### 1.3 사용자 경계 (SER-002, [ADR-0010](adr/0010-composite-fk-user-boundary.md))

부모를 참조하는 FK는 항상 `(user_id, parent_id) → parent (user_id, id)` 복합 키로 건다. FK 검사는 RLS를 거치지 않으므로, 단일 키 FK면 다른 사용자의 강의 ID를 넣어도 막을 수 없다. 복합 키면 DB가 막는다.

```sql
FOREIGN KEY (user_id, lecture_id) REFERENCES lectures (user_id, id) ON DELETE CASCADE
```

모든 FK에는 `(user_id, parent_id)` 인덱스를 둔다. RLS가 `user_id = ?` 조건을 붙이므로 이 인덱스가 부모별 조회에도 쓰인다.

### 1.4 RLS

```sql
CREATE FUNCTION app_user_id() RETURNS bigint LANGUAGE sql STABLE
  AS $$ SELECT current_setting('app.user_id')::bigint $$;

-- 모든 사용자 테이블
ALTER TABLE t ENABLE ROW LEVEL SECURITY;
ALTER TABLE t FORCE ROW LEVEL SECURITY;
CREATE POLICY own ON t
  USING (user_id = (SELECT app_user_id()))
  WITH CHECK (user_id = (SELECT app_user_id()));

-- deletion_batch_id가 있는 테이블 (9장 D2)
CREATE POLICY hide_trash ON t AS RESTRICTIVE FOR SELECT
  USING (deletion_batch_id IS NULL
         OR (SELECT current_setting('app.trash', true)) = 'on');
```

- `app.user_id`를 설정하지 않은 트랜잭션은 오류가 난다. 빠뜨리면 빈 결과가 아니라 실패로 드러난다.
- UPDATE는 기존 행과 **새 행** 모두 SELECT 정책을 거친다. 그래서 휴지통으로 옮기기, 휴지통 조회, 복원은 모두 `SET LOCAL app.trash = 'on'`을 켠 트랜잭션에서만 된다(실제 DB에서 확인).

**DB 역할**

| 역할 | 쓰는 곳 | 권한 |
|---|---|---|
| `notree_owner` | 마이그레이션 | 테이블 소유 |
| `notree_app` | `api`, `realtime`, `worker` | `NOBYPASSRLS`. 바꾸지 않는 테이블은 열 단위 UPDATE만 준다(1.5) |
| `notree_admin` | `cron`, 복원 작업 | `BYPASSRLS` |
| `notree_definer` | 아래 `SECURITY DEFINER` 함수의 소유자. 로그인 불가 | `BYPASSRLS`, 함수가 쓰는 테이블에만 권한 |

사용자를 모르는 시점에 필요한 조회는 `SECURITY DEFINER` 함수로만 연다. 함수는 필요한 값 하나만 돌려준다. 테이블 소유자 `notree_owner`도 `FORCE ROW LEVEL SECURITY`를 받으므로, 함수는 RLS를 우회하는 별도 역할이 소유한다.

- `account.resolve_session(token_hash) → user_id`: 요청마다 세션 확인
- `account.upsert_google_user(sub, email) → user_id`: 로그인
- `platform.claim_stale_jobs() → (job_id, user_id)[]`: 회수 루프(30초)
- `platform.global_spend(utc_date) → numeric`: 전체 하루 한도

### 1.5 바꾸지 않는 기록

`block_revisions`, `note_versions`, `context_versions`, `segment_corrections`, `attempts`, `observations`, `gradings`, `review_item_versions`는 `notree_app`에 UPDATE를 주지 않는다. 바뀌어야 하는 열만 열 단위로 준다.

```sql
GRANT UPDATE (deletion_batch_id) ON block_revisions TO notree_app;
GRANT UPDATE (deletion_batch_id, superseded_at, superseded_by_id) ON observations TO notree_app;
```

### 1.6 휴지통과 삭제 묶음 (DAR-006, SFR-013·048)

- 삭제할 수 있는 행에는 `deletion_batch_id bigint`가 있다. NULL이면 살아 있는 자료다.
- 삭제할 때 영향 범위의 행 전부에 같은 묶음 ID를 쓴다. 이미 다른 묶음 ID가 있는 행은 덮어쓰지 않는다. 그래서 복원은 `WHERE deletion_batch_id = ?` 한 줄이고, 그 전에 따로 지운 자료는 삭제 상태로 남는다(SFR-048 4).
- 영구 삭제는 `cron`이 묶음 단위로 한다. 소유 관계 FK는 `ON DELETE CASCADE`다.
- **탈퇴**는 행에 묶음 ID를 쓰지 않는다. `users.status`와 세션 철회로 접근을 막고, 유예가 끝나면 `users` 행을 지워 전부 cascade로 삭제한다.

### 1.7 세대 번호 (ADR-0006)

반영 대상 행(`users`, `courses`, `lectures`, `notes`, `conversations`, `review_items`)에 `generation int NOT NULL DEFAULT 0`을 둔다. 삭제·취소·잠금 해제·탈퇴 때 올린다. 작업은 시작할 때의 값을 `jobs.target_generation`에 적고, 커밋 트랜잭션에서 대상 행을 `FOR UPDATE`로 잠근 뒤 비교한다.

## 2. account

```sql
CREATE TABLE users (
  id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  google_sub    text NOT NULL UNIQUE,
  email         text NOT NULL,
  display_name  text,
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active','withdrawing')),
  withdraw_requested_at timestamptz,
  purge_at      timestamptz,              -- 탈퇴 유예 끝 = 요청 + 7일
  generation    int NOT NULL DEFAULT 0,   -- 탈퇴 때 올려 진행 중 작업을 무효화
  created_at    timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'withdrawing') = (purge_at IS NOT NULL))
);
-- RLS: id = app_user_id()

CREATE TABLE auth_sessions (
  -- 공통
  token_hash    bytea NOT NULL UNIQUE,    -- sha256(쿠키 값). 원래 값은 저장하지 않는다
  last_seen_at  timestamptz NOT NULL DEFAULT now(),
  expires_at    timestamptz NOT NULL,
  revoked_at    timestamptz,              -- 철회 시점 = 이 값이 커밋된 순간(SFR-044 6)
  revoke_reason text CHECK (revoke_reason IN ('logout','logout_all','withdraw','expired')),
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);
CREATE INDEX ON auth_sessions (user_id) WHERE revoked_at IS NULL;

CREATE TABLE consents (                   -- COR-004·005. 추가만 한다
  -- 공통
  kind           text NOT NULL CHECK (kind IN ('recording_permission','external_processing')),
  notice_version text NOT NULL,           -- 고지 문구 판
  withdrawn_at   timestamptz,
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);

CREATE TABLE user_settings (              -- SFR-040, SFR-038 4
  user_id        bigint PRIMARY KEY REFERENCES users ON DELETE CASCADE,
  daily_minutes  int NOT NULL DEFAULT 20,
  daily_new      int NOT NULL DEFAULT 5,
  daily_reviews  int NOT NULL DEFAULT 20,
  review_email   boolean NOT NULL DEFAULT false
);
```

## 3. capture

```sql
CREATE TABLE courses (
  -- 공통
  name                  text NOT NULL,
  last_reserved_minutes int NOT NULL DEFAULT 60 CHECK (last_reserved_minutes IN (60,120,180)),  -- SFR-002 2
  generation            int NOT NULL DEFAULT 0,
  deletion_batch_id     bigint,
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);

CREATE TABLE context_versions (           -- 맥락 버전. 바꾸지 않는다
  -- 공통
  course_id   bigint NOT NULL,
  version_no  int NOT NULL,
  background  text NOT NULL DEFAULT '',
  terms       text[] NOT NULL DEFAULT '{}',
  UNIQUE (course_id, version_no),
  CHECK (cardinality(terms) <= 200),
  CHECK (char_length(array_to_string(terms, '')) <= 4000),   -- 용어당 40자는 앱에서 검사
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE
);
-- 과목의 최신 맥락 버전 = max(version_no). 따로 가리키는 열을 두지 않는다.

CREATE TABLE lectures (
  -- 공통
  course_id         bigint NOT NULL,      -- SFR-012(후속) 이동 때 바뀐다
  title             text NOT NULL,
  generation        int NOT NULL DEFAULT 0,
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE
);

CREATE TABLE recording_sessions (         -- 녹음 세션 (ADR-0002)
  -- 공통
  lecture_id          bigint NOT NULL,
  seq                 int NOT NULL,       -- 강의 안 순서
  context_version_id  bigint NOT NULL,    -- 시작 시점에 고정 (SFR-001 2)
  status              text NOT NULL CHECK (status IN
                        ('recording','paused','finalizing','completed','partial','failed')),
  reserved_minutes    int NOT NULL CHECK (reserved_minutes IN (60,120,180)),
  started_at          timestamptz NOT NULL,
  ended_at            timestamptz,        -- DAR-001 4의 세 조건 중 먼저 온 시각
  end_reason          text CHECK (end_reason IN
                        ('user','other_device','disconnect_5m','limit_180m','reservation',
                         'budget','system_stop','logout','withdraw')),
  audio_expires_at    timestamptz,        -- ended_at + 7일. 재처리·복원으로 늦추지 않는다
  last_audio_saved_at timestamptz,        -- '마지막 서버 저장 시각' (DAR-001 5)
  deletion_batch_id   bigint,
  UNIQUE (lecture_id, seq),
  CHECK ((ended_at IS NULL) = (audio_expires_at IS NULL)),
  FOREIGN KEY (user_id, lecture_id) REFERENCES lectures (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, context_version_id) REFERENCES context_versions (user_id, id)
);
-- 계정당 녹음 1개 (PER-003 5)
CREATE UNIQUE INDEX one_active_recording ON recording_sessions (user_id)
  WHERE status IN ('recording','paused');

CREATE TABLE stt_sessions (               -- STT 세션 (ADR-0003)
  -- 공통
  recording_session_id bigint NOT NULL,
  context_version_id   bigint NOT NULL,   -- 용어 적용으로 교체되면 새 버전
  opened_at            timestamptz NOT NULL,
  closed_at            timestamptz,
  close_reason         text CHECK (close_reason IN
                         ('finished','reconnect','term_swap','long_pause','failed')),
  deletion_batch_id    bigint,
  FOREIGN KEY (user_id, recording_session_id) REFERENCES recording_sessions (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, context_version_id) REFERENCES context_versions (user_id, id)
);

CREATE TABLE transcript_segments (        -- 전사 구간 = 닫힌 발화 하나 (9장 D8, SFR-004 3)
  -- 공통
  lecture_id           bigint NOT NULL,
  recording_session_id bigint NOT NULL,
  stt_session_id       bigint NOT NULL,   -- → 맥락 버전 (전사 구간마다 사용한 버전, SFR-001 2)
  start_ms             int NOT NULL,      -- 녹음 세션 음성 기준
  end_ms               int NOT NULL,
  stt_text             text,              -- STT 원본. 정정 확정 7일 뒤 NULL
  stt_text_purge_at    timestamptz,
  maybe_duplicate      boolean NOT NULL DEFAULT false,   -- 중복 가능 구간
  close_reason         text NOT NULL CHECK (close_reason IN
                         ('endpoint','max_15s','pause','stop','stt_swap')),
  closed_at            timestamptz NOT NULL,             -- 구간이 닫힌 시각
  committed_at         timestamptz NOT NULL DEFAULT now(),
  deletion_batch_id    bigint,
  CHECK (end_ms >= start_ms),
  FOREIGN KEY (user_id, recording_session_id) REFERENCES recording_sessions (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, stt_session_id) REFERENCES stt_sessions (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, lecture_id) REFERENCES lectures (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON transcript_segments (user_id, recording_session_id, start_ms);
CREATE INDEX ON transcript_segments (stt_text_purge_at) WHERE stt_text_purge_at IS NOT NULL;
-- '저장 지연' = committed_at - closed_at > 1초. 열로 두지 않는다.
-- 닫힌 구간만 저장하고 바꾸지 않으므로 덧붙은 전사는 앞부분을 무효로 만들지 않는다 (DAR-005 4).
-- 열린 구간은 realtime 메모리에만 있다. 서버가 죽어 잃으면 누락 구간이 되고 음성으로 재전사한다 (SFR-004 5).
-- 60분 강의 약 400~700행, 동시 녹음 10개 기준 초당 1~2건 insert.

CREATE TABLE segment_corrections (        -- 정정 버전. 바꾸지 않는다
  -- 공통
  segment_id    bigint NOT NULL,
  text          text,                     -- NULL = STT 원본으로 되돌림
  suggestion_id bigint,                   -- 수정 제안 수락에서 왔으면
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, segment_id) REFERENCES transcript_segments (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON segment_corrections (user_id, segment_id, id DESC);
-- 구간의 현재 전사 = 가장 최근 정정의 text, 없거나 NULL이면 stt_text.
-- 구간의 버전 = 가장 최근 정정 id (없으면 0). 근거 비교에 쓴다.
-- 정정을 저장하면 segment.stt_text_purge_at = now() + 7일, 원본으로 되돌리면 NULL.

CREATE TABLE correction_suggestions (     -- 수정 제안 (SFR-058)
  -- 공통
  lecture_id      bigint NOT NULL,
  segment_id      bigint NOT NULL,
  note_version_id bigint NOT NULL,        -- 만든 최종 노트 버전
  original_text   text NOT NULL,
  suggested_text  text NOT NULL,
  reason          text NOT NULL CHECK (reason IN ('misrecognition','awkward')),
  status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','accepted','rejected','edited','superseded')),
  resolved_at     timestamptz,
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, segment_id) REFERENCES transcript_segments (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, lecture_id) REFERENCES lectures (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON correction_suggestions (user_id, segment_id);
-- 같은 구간에 rejected가 있으면 새 제안을 저장하지 않는다 (SFR-058 6).

CREATE TABLE term_candidates (            -- SFR-046 2
  -- 공통
  course_id     bigint NOT NULL,
  correction_id bigint NOT NULL,
  term          text NOT NULL CHECK (char_length(term) <= 40),
  status        text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','accepted','dismissed')),
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, correction_id) REFERENCES segment_corrections (user_id, id) ON DELETE CASCADE
);

CREATE TABLE audio_chunks (               -- S3 키와 크기만. 음성은 S3 audio 버킷
  -- 공통
  recording_session_id bigint NOT NULL,
  seq          int NOT NULL,
  start_ms     int NOT NULL,
  duration_ms  int NOT NULL,
  s3_key       text NOT NULL UNIQUE,
  bytes        int NOT NULL,
  saved_at     timestamptz NOT NULL,      -- 내구 저장·재생 가능 확인 시각
  source       text NOT NULL DEFAULT 'live' CHECK (source IN ('live','recovery_upload')),
  deletion_batch_id bigint,
  UNIQUE (recording_session_id, seq),
  FOREIGN KEY (user_id, recording_session_id) REFERENCES recording_sessions (user_id, id) ON DELETE CASCADE
);
-- 만료는 recording_sessions.audio_expires_at으로 판단한다. 조각마다 복사하지 않는다.

CREATE TABLE recording_gaps (             -- 의도적 정지와 누락 구간 (SFR-003 1, SFR-004 5)
  -- 공통
  recording_session_id bigint NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('pause','missing')),
  start_ms    int NOT NULL,
  end_ms      int,
  cause       text CHECK (cause IN ('stt_failed','network','buffer_full','save_failed','server_crash')),  -- server_crash: 열린 구간 유실 (SFR-004 5)
  has_audio   boolean NOT NULL DEFAULT false,   -- 음성이 있어 재전사할 수 있음 (SIR-001 4)
  retranscribed_at timestamptz,
  deletion_batch_id bigint,
  CHECK ((kind = 'missing') = (cause IS NOT NULL)),
  FOREIGN KEY (user_id, recording_session_id) REFERENCES recording_sessions (user_id, id) ON DELETE CASCADE
);
```

## 4. notebook

ADR-0007의 두 층 구조다. `block_revisions`는 블록 하나의 내용이고 바꾸지 않는다. `note_versions`는 리비전 ID의 순서 배열이다. 노트의 현재 상태는 `notes.current_version_id`가 가리키는 버전이다.

```sql
CREATE TABLE notes (
  -- 공통
  kind              text NOT NULL CHECK (kind IN ('lecture','course')),  -- 실시간 요약은 DB에 없다 (9장 D6)
  course_id         bigint,               -- kind = 'course'일 때만
  lecture_id        bigint,               -- 나머지
  current_version_id bigint,              -- 마지막 completed·partial 버전
  generation        int NOT NULL DEFAULT 0,
  locked_until      timestamptz,          -- 과목 노트 업데이트 편집 잠금. 20초마다 연장, 60초 임대 (QUR-002 3)
  lock_update_id    bigint,
  deletion_batch_id bigint,
  CHECK ((kind = 'course') = (course_id IS NOT NULL)),
  CHECK ((kind = 'course') = (lecture_id IS NULL)),
  UNIQUE (lecture_id, kind),
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, lecture_id) REFERENCES lectures (user_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX one_course_note ON notes (course_id) WHERE kind = 'course';
-- 편집 가능 = locked_until IS NULL OR locked_until < now()

CREATE TABLE blocks (                     -- 위치가 바뀌어도 같은 블록 (DAR-002 1)
  id                uuid PRIMARY KEY,     -- 편집기가 만든다 (9장 D1)
  user_id           bigint NOT NULL,
  note_id           bigint NOT NULL,
  created_at        timestamptz NOT NULL DEFAULT now(),
  deletion_batch_id bigint,
  UNIQUE (user_id, id),
  FOREIGN KEY (user_id, note_id) REFERENCES notes (user_id, id) ON DELETE CASCADE
);

CREATE TABLE block_revisions (            -- 바꾸지 않는다
  -- 공통
  block_id            uuid NOT NULL,
  kind                text NOT NULL CHECK (kind IN
                        ('paragraph','heading','list_item','code','table','supplement')),
  content             jsonb NOT NULL,     -- 형식은 9장 D7
  attrs               jsonb NOT NULL DEFAULT '{}',   -- 요약 라벨(반복·보완·정정), 최종 노트 역할(개념·예시·복습 포인트·확인 필요)
  author              text NOT NULL CHECK (author IN ('ai','user','qa')),   -- SFR-022
  reason              text,               -- 변경 이유 (SFR-010 2)
  evidence_unverified boolean NOT NULL DEFAULT false,   -- '근거 미확인' (출처 검증 실패)
  job_id              bigint,
  note_change_id      bigint,
  deletion_batch_id   bigint,
  FOREIGN KEY (user_id, block_id) REFERENCES blocks (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON block_revisions (user_id, block_id, id DESC);
-- 보호 블록 (SFR-009 4) = author = 'user'인 리비전이 하나라도 있는 블록. 열로 두지 않는다.

CREATE TABLE note_versions (              -- 바꾸지 않는다
  -- 공통
  note_id            bigint NOT NULL,
  version_no         int NOT NULL,
  block_revision_ids bigint[] NOT NULL,   -- 블록 트리의 전위 순서 (ADR-0020)
  depths             smallint[] NOT NULL, -- 같은 자리 블록의 깊이. 첫 항목 0, 앞 항목보다 최대 1 깊게(앱 검사)
  kind               text NOT NULL CHECK (kind IN
                       ('final','correction','edit','course_update','qa_change','revert','restore','rewrite')),
                       -- correction: 수정 제안 검토 완료 뒤 재생성 (SFR-058 5)
  status             text NOT NULL DEFAULT 'completed' CHECK (status IN ('completed','partial')),
  based_on_id        bigint,              -- 복원·되돌리기의 원본
  job_id             bigint,
  deletion_batch_id  bigint,
  UNIQUE (note_id, version_no),
  CHECK (cardinality(depths) = cardinality(block_revision_ids)),
  FOREIGN KEY (user_id, note_id) REFERENCES notes (user_id, id) ON DELETE CASCADE
);
-- 들여쓰기·이동은 depths와 순서만 바뀐 새 버전이다. 새 리비전을 만들지 않는다.
-- 생성 중·실패는 jobs에만 있다. 실패하면 current_version_id가 그대로라 기존 완료본이 유지된다 (SFR-015 1).
-- 사용자 편집은 저장할 때마다 새 버전 (9장 D4).

CREATE TABLE citations (                  -- 근거
  -- 공통
  -- 무엇의 근거인가: 셋 중 하나
  block_revision_id     bigint,
  message_id            bigint,
  item_version_id       bigint,
  -- 무엇에 기대는가
  kind                  text NOT NULL CHECK (kind IN ('lecture','note','web','general')),
  segment_id            bigint,           -- kind = 'lecture'
  segment_version       bigint,           -- 인용 당시 구간 버전 (정정 id, 원본이면 0)
  source_revision_id    bigint,           -- kind = 'note': 강의 노트 블록 리비전
  web_url               text,
  web_title             text,
  web_fetched_at        timestamptz,
  CHECK (num_nonnulls(block_revision_id, message_id, item_version_id) = 1),
  CHECK (kind <> 'web' OR (web_url IS NOT NULL AND web_fetched_at IS NOT NULL)),
  FOREIGN KEY (user_id, block_revision_id) REFERENCES block_revisions (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, message_id) REFERENCES messages (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, item_version_id) REFERENCES review_item_versions (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, segment_id) REFERENCES transcript_segments (user_id, id) ON DELETE SET NULL (segment_id),
  FOREIGN KEY (user_id, source_revision_id) REFERENCES block_revisions (user_id, id) ON DELETE SET NULL (source_revision_id)
);
CREATE INDEX ON citations (user_id, segment_id) WHERE segment_id IS NOT NULL;
CREATE INDEX ON citations (user_id, source_revision_id) WHERE source_revision_id IS NOT NULL;
-- 근거 원본이 영구 삭제되면 FK가 NULL이 되고 행은 남는다 → '출처 삭제됨'.

CREATE TABLE note_updates (               -- 과목 노트 업데이트 (SFR-008)
  -- 공통
  note_id         bigint NOT NULL,
  trigger         text NOT NULL CHECK (trigger IN ('lecture_final','rewrite','retry')),
  status          text NOT NULL CHECK (status IN
                    ('queued','running','paused','failed','awaiting_user','completed','cancelled')),
  note_generation int NOT NULL,
  run_seconds     int NOT NULL DEFAULT 0, -- 연속 실행 10분이면 paused
  result_version_id bigint,
  failed_stage    text,
  error_code      text,
  started_at      timestamptz,
  finished_at     timestamptz,
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, note_id) REFERENCES notes (user_id, id) ON DELETE CASCADE
);
-- 과목 노트당 실행 중 1, 재개 대기 1, 대기 요청 1
CREATE UNIQUE INDEX ON note_updates (note_id) WHERE status = 'running';
CREATE UNIQUE INDEX ON note_updates (note_id) WHERE status IN ('paused','failed');
CREATE UNIQUE INDEX ON note_updates (note_id) WHERE status = 'queued';
-- 대기 요청이 이미 있으면 새 요청은 그 행에 합친다. 반영할 강의 버전은 시작할 때 정한다.
-- id가 LangGraph 체크포인트의 thread_id다. 재개는 체크포인터가 하고, 의미 충돌은 interrupt로 awaiting_user가 된다 (9장 D9, ADR-0023).
-- 이중 반영은 반영 노드가 노트 변경과 status = 'completed'를 한 트랜잭션으로 커밋하고, 이미 completed면 건너뛰어 막는다.
-- 단원 = 최상위 제목 블록과 다음 최상위 제목 앞까지의 블록. 그 제목 블록 ID로 식별하고, 배치 계획은 체크포인트에 남는다.

CREATE TABLE note_changes (               -- 변경안. notebook 소유. tutor는 제출만 한다 (architecture 3장)
  -- 공통
  note_id          bigint NOT NULL,       -- 과목 노트 또는 강의 노트
  origin           text NOT NULL CHECK (origin IN ('course_update','lecture_regen','qa','revert')),
  note_update_id   bigint,                -- course_update
  job_id           bigint,                -- lecture_regen: 강의 노트 재생성 작업 (SFR-022)
  message_id       bigint,                -- qa
  reverts_id       bigint,                -- revert: 되돌리는 변경 (SFR-049)
  op               text NOT NULL CHECK (op IN ('add','modify','supplement','delete','merge')),
  target_block_id  uuid,                  -- 고정 블록 식별자 (SFR-019 2)
  base_revision_id bigint,                -- 판단 기준 리비전. 반영 때 현재 리비전과 비교
  proposal         jsonb NOT NULL,        -- 새 내용·위치
  decision         text NOT NULL CHECK (decision IN ('auto','confirm','hold')),   -- SFR-020 1
  status           text NOT NULL CHECK (status IN
                     ('waiting','pending','applied','rejected','reverted','superseded')),
  wait_reason      text CHECK (wait_reason IN
                     ('note_updating','lecture_incomplete','lecture_failed','cap_exceeded','conflict')),
  merge_outcome    text CHECK (merge_outcome IN ('kept','merged','conflict','invalidated')),  -- SFR-022 1
  reason           text CHECK (char_length(reason) <= 300),
  applied_version_id bigint,
  resolved_at      timestamptz,
  deletion_batch_id bigint,
  CHECK (num_nonnulls(note_update_id, job_id, message_id, reverts_id) = 1),
  FOREIGN KEY (user_id, note_id) REFERENCES notes (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON note_changes (user_id, note_id) WHERE status = 'waiting';
-- 대기 상한 20 (SFR-020 5·7): status = 'waiting' AND wait_reason IN ('note_updating','lecture_incomplete') 개수

CREATE TABLE search_entries (             -- 검색 자료. 원본에서 다시 만들 수 있다 (DAR-005 3)
  -- 공통
  course_id         bigint NOT NULL,
  lecture_id        bigint,
  block_id          uuid,
  block_revision_id bigint,
  segment_id        bigint,
  segment_version   bigint,
  body              text NOT NULL,        -- 키워드 검색용 평문
  embedding         vector(1536),         -- 의미 검색. text-embedding-3-small 기본 차원. 생성 전이나 실패면 NULL
  embedding_model   text,                 -- 'text-embedding-3-small'. 모델을 바꾸면 전부 다시 만든다
  deletion_batch_id bigint,
  CHECK (num_nonnulls(block_id, segment_id) = 1),
  CHECK ((embedding IS NULL) = (embedding_model IS NULL)),
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON search_entries USING gin (body gin_bigm_ops);
CREATE INDEX ON search_entries USING hnsw (embedding vector_cosine_ops);
-- Q&A는 두 결과를 합친다(예: 순위 역수 합). 노트 검색 화면(SFR-047)은 키워드 결과가 기본이다.
-- RLS가 user_id와 휴지통을 거른 뒤 HNSW가 돈다. 한 사용자 자료가 적으면 결과가 모자랄 수 있으니
-- pgvector의 반복 스캔(iterative scan) 설정을 켜거나 ef_search를 키운다.
CREATE UNIQUE INDEX ON search_entries (block_id) WHERE block_id IS NOT NULL;
CREATE UNIQUE INDEX ON search_entries (segment_id) WHERE segment_id IS NOT NULL;
-- 조회할 때 원본의 현재 버전과 다시 비교한다 (DAR-005 1). 다르면 결과에서 뺀다.
-- 갱신 중·실패 상태는 search_refresh 작업의 상태다 (DAR-005 2).
```

### 4.1 블록 근거 상태는 계산한다 (9장 D3)

'갱신 필요'와 '출처 삭제됨'을 열로 저장하지 않고, 인용한 버전과 원본의 현재 버전을 비교해 구한다. 근거가 바뀔 때마다 상태를 퍼뜨리는 작업이 필요 없고, 퍼뜨리다 빠뜨리는 일도 없다.

| 근거 종류 | 출처 삭제됨 | 갱신 필요 |
|---|---|---|
| `lecture` | `segment_id IS NULL`, 또는 구간이 휴지통에 있음 | `segment_version` ≠ 구간의 현재 버전 |
| `note` | `source_revision_id IS NULL`, 블록이 휴지통에 있음, 또는 블록이 강의 노트 현재 버전에서 빠짐 | 같은 블록의 다른 리비전이 현재 버전에 있음 |
| `web`, `general` | — | — |

- 블록의 상태 = 현재 리비전이 가진 근거 중 가장 나쁜 상태다. 하나라도 나쁘면 Q&A·출제 근거에서 뺀다(SFR-008 3).
- STT 원본이 지워져도 `segment_version`은 원본(0)을 가리키고 구간의 현재 버전은 정정 id이므로, '갱신 필요'가 유지되고 '출처 삭제됨'이 되지 않는다(SFR-046 1).
- 강의를 다른 과목으로 옮긴 경우(SFR-012, 후속)는 `lecture.course_id`와 노트의 과목을 비교하는 조건을 하나 더 넣는다.

## 5. tutor

```sql
CREATE TABLE conversations (              -- 대화
  -- 공통
  course_id         bigint NOT NULL,
  title             text,
  summary           text,                 -- 대화 요약. 질문 속 개인 사실을 옮기지 않는다 (SER-001 3)
  summary_upto_id   bigint,               -- 요약이 덮는 마지막 메시지
  generation        int NOT NULL DEFAULT 0,
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE
);

CREATE TABLE messages (                   -- 질문 원문은 여기에만 둔다 (SER-001)
  -- 공통
  conversation_id bigint NOT NULL,
  role            text NOT NULL CHECK (role IN ('user','assistant')),
  content         text,                   -- 질문 원문 또는 완료된 답변. 미완성 답변은 저장하지 않는다
  question_id     bigint,                 -- 답변 → 질문
  answer_status   text CHECK (answer_status IN
                    ('generating','completed','interrupted','failed','evidence_changed')),
  reflect_need    text CHECK (reflect_need IN ('needed','not_needed','hold')),   -- SFR-017
  reflect_reason  text CHECK (char_length(reflect_reason) <= 300),
  reflect_status  text CHECK (reflect_status IN ('pending','applied','held','failed')),  -- SFR-021
  learner_status  text CHECK (learner_status IN ('not_needed','pending','applied','held','failed')),
  answer_kind     text CHECK (answer_kind IN ('answer','clarification','conflict')),   -- 답변 종류
  truncated       boolean NOT NULL DEFAULT false,   -- 맥락 자료나 출력을 잘랐음 (PER-004 4)
  evidence_as_of  timestamptz,            -- 녹음 중 확정 전사의 기준 시각 (SFR-016 3)
  completed_at    timestamptz,
  deletion_batch_id bigint,
  CHECK (role = 'assistant' OR (answer_status IS NULL AND question_id IS NULL)),
  CHECK (role = 'user' OR question_id IS NOT NULL),
  CHECK (answer_status = 'completed' OR role = 'user' OR content IS NULL),
  FOREIGN KEY (user_id, conversation_id) REFERENCES conversations (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, question_id) REFERENCES messages (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON messages (user_id, conversation_id, id);
-- answer_status·reflect_status·learner_status는 qa_answer 작업의 단계 완료 표시다. 각 단계 결과와 같은 트랜잭션에서 쓰고,
-- 인계·재시도 때 이 값을 보고 남은 단계만 한다. 반영·관찰 단계는 answer_status = 'completed'일 때만 돈다 (9장 D11).
-- 확인 질문·상충 안내 답변(answer_kind = 'clarification'·'conflict')은 저장 트랜잭션에서 reflect_need·learner_status를 'not_needed'로 쓰고 두 단계를 건너뛴다.
```

## 6. learner

```sql
CREATE TABLE concepts (                   -- 9장 D5
  -- 공통
  course_id         bigint NOT NULL,
  name              text NOT NULL,
  key               text NOT NULL,        -- 정규화한 이름
  merged_into_id    bigint,
  deletion_batch_id bigint,
  UNIQUE (course_id, key),
  FOREIGN KEY (user_id, course_id) REFERENCES courses (user_id, id) ON DELETE CASCADE
);

CREATE TABLE observations (               -- 관찰. 바꾸지 않는다 (DAR-003)
  -- 공통
  concept_id       bigint NOT NULL,
  grading_id       bigint,                -- 복습 관찰: 채점 결과에서
  message_id       bigint,                -- Q&A 관찰: 질문에서
  observed_at      timestamptz NOT NULL,
  kind             text NOT NULL CHECK (kind IN
                     ('independent_success','success','partial','strong_failure','misconception','stated_confusion')),
  strength         text NOT NULL CHECK (strength IN ('strong','weak')),
  item_type        text CHECK (item_type IN ('essay','short','mcq','flashcard','qa')),
  hint_used        boolean NOT NULL DEFAULT false,
  answer_revealed  boolean NOT NULL DEFAULT false,
  uncertainty      real,
  dedupe_key       text NOT NULL,         -- 같은 관찰 중복 반영 방지 (SFR-025 7)
  superseded_at    timestamptz,           -- 재평가로 '대체됨'
  superseded_by_id bigint,
  deletion_batch_id bigint,
  UNIQUE (user_id, dedupe_key),
  CHECK (num_nonnulls(grading_id, message_id) = 1),
  FOREIGN KEY (user_id, concept_id) REFERENCES concepts (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, grading_id) REFERENCES gradings (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, message_id) REFERENCES messages (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON observations (user_id, concept_id, observed_at) WHERE superseded_at IS NULL;
-- 원문 열이 없다. 질문 원문은 message_id로만 닿는다 (SFR-024 1).
-- 출처(채점·메시지)와 함께 cascade로 지워지고 같은 묶음 ID로 복원된다 (DAR-003 4).

CREATE TABLE concept_states (             -- 이해 상태. 유효한 관찰에서 다시 계산하는 캐시
  user_id     bigint NOT NULL,
  concept_id  bigint NOT NULL,
  state       text NOT NULL DEFAULT 'unassessed'
                CHECK (state IN ('unassessed','learning','confirmed','recheck')),
  last_independent_success_at timestamptz,
  last_strong_failure_at      timestamptz,
  basis       jsonb NOT NULL DEFAULT '[]', -- 근거 관찰 id (SFR-027, SFR-042)
  computed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, concept_id),
  FOREIGN KEY (user_id, concept_id) REFERENCES concepts (user_id, id) ON DELETE CASCADE
);
```

## 7. review

```sql
CREATE TABLE review_units (               -- 복습 단위 (SFR-032 4). FSRS 상태는 유효한 review_logs에서 다시 만드는 캐시
                                          -- 재평가(SFR-027)하면 그 단위의 유효 로그를 시간순으로 다시 적용한다
  -- 공통
  concept_id      bigint NOT NULL,
  objective       text NOT NULL,          -- 학습 목표
  task_kind       text NOT NULL CHECK (task_kind IN ('recall','explain','distinguish','apply')),
  response_mode   text NOT NULL CHECK (response_mode IN ('choose','produce')),
  rubric_major    int NOT NULL,           -- 평가 기준 주 버전
  status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','stopped','retired')),
  replaced_by_id  bigint,                 -- 의미가 바뀌어 은퇴할 때 새 단위
  fsrs_state      text NOT NULL DEFAULT 'new' CHECK (fsrs_state IN ('new','learning','review','relearning')),
  stability       double precision,
  difficulty      double precision,
  step            int,
  due_at          timestamptz,            -- 도래 = due_at <= now()
  postponed_until timestamptz,            -- 연기 (SFR-039). 등급으로 기록하지 않는다
  skip_until      date,                   -- 건너뜀: KST 날짜까지 추천에서 뺀다
  last_review_at  timestamptz,
  reps            int NOT NULL DEFAULT 0,
  lapses          int NOT NULL DEFAULT 0,
  fsrs_version    text NOT NULL,          -- 라이브러리·파라미터 버전 (SFR-032 1)
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, concept_id) REFERENCES concepts (user_id, id) ON DELETE CASCADE
);
CREATE INDEX due ON review_units (user_id, due_at)
  WHERE status = 'active' AND deletion_batch_id IS NULL;   -- 도래 조회 (PER-005)

CREATE TABLE review_items (               -- 복습 문제
  -- 공통
  unit_id            bigint NOT NULL,
  current_version_id bigint,              -- 지금 제공하는 버전
  status             text NOT NULL DEFAULT 'draft'
                       CHECK (status IN ('draft','active','paused','retired','unavailable')),
  pause_reason       text CHECK (pause_reason IN ('evidence_changed','conflict','user_stopped')),
  generation         int NOT NULL DEFAULT 0,
  deletion_batch_id  bigint,
  FOREIGN KEY (user_id, unit_id) REFERENCES review_units (user_id, id) ON DELETE CASCADE
);
-- 'unavailable' = 문제 준비 불가 (SFR-041 5)

CREATE TABLE review_item_versions (       -- 바꾸지 않는다. 근거는 citations
  -- 공통
  item_id      bigint NOT NULL,
  version_no   int NOT NULL,
  item_type    text NOT NULL CHECK (item_type IN ('essay','short','mcq','flashcard')),
  prompt       jsonb NOT NULL,
  answer       jsonb NOT NULL,
  rubric       jsonb NOT NULL,            -- 핵심 요소, 필수 여부, 동의어
  prompt_rev   int NOT NULL,              -- 문제·정답·평가 기준 각각의 버전 (SFR-034 1)
  answer_rev   int NOT NULL,
  rubric_rev   int NOT NULL,
  change       text NOT NULL CHECK (change IN ('new','wording','regenerated')),
  activated_at timestamptz,               -- 활성화 순간 근거를 다시 확인 (SFR-034 3)
  job_id       bigint,
  deletion_batch_id bigint,
  UNIQUE (item_id, version_no),
  FOREIGN KEY (user_id, item_id) REFERENCES review_items (user_id, id) ON DELETE CASCADE
);

CREATE TABLE answer_drafts (              -- SFR-052. 화면마다 한 행
  -- 공통
  item_version_id bigint NOT NULL,
  client_id       text NOT NULL,          -- 화면(탭) 식별
  content         text NOT NULL,
  rev             int NOT NULL DEFAULT 1, -- 낙관적 동시성
  stale           boolean NOT NULL DEFAULT false,   -- '이전 문제 기준'
  updated_at      timestamptz NOT NULL DEFAULT now(),
  deletion_batch_id bigint,
  UNIQUE (item_version_id, client_id),
  FOREIGN KEY (user_id, item_version_id) REFERENCES review_item_versions (user_id, id) ON DELETE CASCADE
);
-- 한 문제에 화면이 둘 이상이면 행이 둘 이상 남고, 화면이 둘 다 보여 고르게 한다 (SFR-052 4).

CREATE TABLE attempts (                   -- 제출 답안. 바꾸지 않는다 (SFR-052 8)
  -- 공통
  item_version_id        bigint NOT NULL,
  unit_id                bigint NOT NULL,
  answer                 text,            -- 플래시카드는 NULL
  self_rating            text CHECK (self_rating IN ('again','hard','good','easy')),
  hints                  jsonb NOT NULL DEFAULT '[]',   -- [{kind, at}]
  answer_revealed        boolean NOT NULL DEFAULT false,
  revealed_before_recall boolean NOT NULL DEFAULT false,
  presented_at           timestamptz NOT NULL,          -- 실제 제공 시각 (SFR-037 4)
  idempotency_key        uuid NOT NULL UNIQUE,          -- 화면이 만든다
  deletion_batch_id      bigint,
  FOREIGN KEY (user_id, item_version_id) REFERENCES review_item_versions (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, unit_id) REFERENCES review_units (user_id, id) ON DELETE CASCADE
);
-- submitted_at = created_at

CREATE TABLE gradings (                   -- 평가 버전. 재평가는 새 행 (DAR-004 4)
  -- 공통
  attempt_id          bigint NOT NULL,
  version_no          int NOT NULL,
  cause               text NOT NULL CHECK (cause IN ('initial','regrade','recheck')),
  rubric_rev          int NOT NULL,       -- 어느 평가 기준으로 (DAR-004 1)
  status              text NOT NULL CHECK (status IN ('pending','completed','held','failed')),
  held_reason         text,
  element_scores      jsonb,              -- [{element, required, score 0|0.5|1}]
  verdict             text CHECK (verdict IN ('met','missing','partial','misconception')),
  major_misconception boolean,
  passed              boolean,
  rating              text CHECK (rating IN ('again','hard','good','easy')),
  feedback            jsonb,              -- 충족·누락·오개념, 지적마다 근거 블록 (SFR-053)
  applied_at          timestamptz,        -- 이해 상태·일정 반영 완료. 평가와 반영을 나눈다 (SFR-036 1)
  superseded_at       timestamptz,
  deletion_batch_id   bigint,
  UNIQUE (attempt_id, version_no),
  FOREIGN KEY (user_id, attempt_id) REFERENCES attempts (user_id, id) ON DELETE CASCADE
);
-- 재평가 3회 (SFR-027 3) = cause = 'regrade' 개수

CREATE TABLE review_logs (                -- FSRS 반영 기록
  -- 공통
  unit_id          bigint NOT NULL,
  grading_id       bigint NOT NULL UNIQUE,   -- 같은 답안 재처리는 한 번만 (SFR-036 2)
  rating           text NOT NULL CHECK (rating IN ('again','hard','good','easy')),
  scheduled_due_at timestamptz,            -- 예정 시각
  reviewed_at      timestamptz NOT NULL,   -- 실제 리뷰 시각
  state_before     jsonb NOT NULL,
  state_after      jsonb NOT NULL,
  fsrs_version     text NOT NULL,
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, unit_id) REFERENCES review_units (user_id, id) ON DELETE CASCADE,
  FOREIGN KEY (user_id, grading_id) REFERENCES gradings (user_id, id) ON DELETE CASCADE
);

CREATE TABLE schedule_events (            -- 연기·건너뜀·중단 이력 (SFR-039)
  -- 공통
  unit_id   bigint NOT NULL,
  kind      text NOT NULL CHECK (kind IN ('postpone','skip','stop','resume','retire')),
  to_time   timestamptz,
  deletion_batch_id bigint,
  FOREIGN KEY (user_id, unit_id) REFERENCES review_units (user_id, id) ON DELETE CASCADE
);

CREATE TABLE email_digests (              -- SFR-038 4·5
  -- 공통
  kst_date    date NOT NULL,
  status      text NOT NULL CHECK (status IN ('sending','accepted','uncertain','failed')),
  provider_id text,
  UNIQUE (user_id, kst_date),             -- 하루 한 번. 불확실해도 다시 보내지 않는다
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);
```

**동시 답안** (SFR-036 3): 채점 반영 트랜잭션은 `review_units` 행을 `FOR UPDATE`로 잠그고, 이해 상태 재계산 전에 `concept_states` 행도 잠근다.

## 8. platform

```sql
CREATE TABLE deletion_batches (           -- 삭제 묶음
  -- 공통
  root_kind   text NOT NULL CHECK (root_kind IN ('course','lecture','note','conversation','review_item')),
  root_id     bigint NOT NULL,
  mode        text NOT NULL CHECK (mode IN ('trash','immediate')),
  scope       jsonb NOT NULL,             -- 확인 화면에 보여 준 종류별 개수 (SFR-013 1)
  purge_at    timestamptz NOT NULL,       -- 기한이 여럿이면 가장 이른 것 (DAR-006 7)
  restored_at timestamptz,
  purged_at   timestamptz,
  logged_at   timestamptz,                -- S3 삭제 기록 확인 시각. 이게 있어야 삭제 완료 (ADR-0008)
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);
CREATE INDEX ON deletion_batches (purge_at) WHERE purged_at IS NULL AND restored_at IS NULL;
-- 모든 deletion_batch_id 열은 이 테이블을 FK로 참조한다 (ON DELETE SET NULL 아님. 영구 삭제가 먼저다).

CREATE TABLE jobs (                       -- 작업 상태의 원본 (ADR-0001, ADR-0017~0019)
  -- 공통
  -- live_summary: 실시간 요약 (SFR-006) · final_note: 강의 최종 노트 (SFR-007) · course_update: 과목 노트 업데이트 (SFR-008)
  -- qa_answer: Q&A 답변 → 노트 반영 → 관찰 단계 (D11) · generate_item: 복습 문항 출제 (SFR-034) · grade: 채점과 관찰 추가 (SFR-035)
  -- search_refresh: 검색 자료 갱신 · retranscribe: 지난 구간 재전사 (SFR-046 5) · email_digest: 복습 알림 메일 (SFR-038)
  -- purge: 보관 기간이 지난 데이터 영구 삭제
  kind              text NOT NULL CHECK (kind IN
                      ('live_summary','final_note','course_update','qa_answer',
                       'generate_item','grade','search_refresh',
                       'retranscribe','email_digest','purge')),
  status            text NOT NULL DEFAULT 'queued' CHECK (status IN
                      ('queued','running','succeeded','failed','cancelled','discarded')),
  target_table      text,
  target_id         bigint,
  target_generation int,
  payload           jsonb NOT NULL DEFAULT '{}',   -- ID만. 원문 금지 (SER-001 2)
  idempotency_key   text,                          -- 클라이언트 요청 식별자 (ADR-0019)
  request_hash      bytea,                         -- 같은 키에 다른 본문이면 409
  stage             text,
  attempt_no        int NOT NULL DEFAULT 0,        -- 실행 시도 번호. 시작·인계 때 증가, 반영 때 확인. 3 초과면 실패 (ADR-0017·0018)
  available_at      timestamptz NOT NULL DEFAULT now(),
  error_code        text,
  started_at        timestamptz,
  finished_at       timestamptz,
  UNIQUE (user_id, idempotency_key),
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);
-- 실행 중 여부(lease)는 Redis에만 있다. 외부 호출 재시도 횟수는 SDK가 세므로 열이 없다.
CREATE UNIQUE INDEX one_qa ON jobs (user_id)                    -- 계정당 Q&A 1 (PER-003 5)
  WHERE kind = 'qa_answer' AND status IN ('queued','running');
CREATE UNIQUE INDEX one_live_summary_running ON jobs (target_id)  -- 강의당 실행 1·대기 1 (SFR-006 5)
  WHERE kind = 'live_summary' AND status = 'running';
CREATE UNIQUE INDEX one_live_summary_queued ON jobs (target_id)
  WHERE kind = 'live_summary' AND status = 'queued';
-- AI 작업 전체 2개는 개수 검사라 인덱스로 못 막는다. 작업 등록 때 users 행을 FOR UPDATE로 잠그고 센다.
-- 계정 한도는 사용자가 시작한 작업에만 센다. 시스템이 이어서 만드는 작업은 종류별 상한으로 묶는다 (9장 D11).

CREATE TABLE outbox (                     -- 보낼 것: 작업 전달과 완료·실패·취소 이벤트 (ADR-0019)
  -- 공통
  kind       text NOT NULL CHECK (kind IN ('dispatch','event')),
  job_id     bigint NOT NULL,
  stream     text NOT NULL,               -- dispatch: 'jobs:qa' | 'jobs:bg', event: 'events:{user_id}'
  payload    jsonb NOT NULL DEFAULT '{}', -- ID와 상태만. 원문 금지 (SER-001 2)
  sent_at    timestamptz,
  FOREIGN KEY (user_id, job_id) REFERENCES jobs (user_id, id) ON DELETE CASCADE
);
CREATE INDEX ON outbox (created_at) WHERE sent_at IS NULL;      -- 회수 루프
-- 도메인 변경·jobs와 같은 트랜잭션에 넣고, 커밋 직후 보내고 sent_at을 채운다. 보낸 행은 7일 뒤 cron이 지운다.
-- RLS: 다른 사용자 테이블과 같은 own 정책. 회수 루프와 정리는 notree_admin 계정으로 돈다.

CREATE TABLE job_stages (                 -- 단계별 소요 시간·실패 사유 (QUR-007 1)
  -- 공통
  job_id     bigint NOT NULL,
  stage      text NOT NULL,
  started_at timestamptz NOT NULL,
  ended_at   timestamptz,
  outcome    text CHECK (outcome IN ('ok','retry','failed','cancelled')),
  error_code text,
  FOREIGN KEY (user_id, job_id) REFERENCES jobs (user_id, id) ON DELETE CASCADE
);

CREATE TABLE ai_calls (                   -- 외부 호출별 사용량 (QUR-007 2)
  -- 공통
  job_id               bigint,
  recording_session_id bigint,
  provider             text NOT NULL CHECK (provider IN ('soniox','openai')),
  model                text,
  input_tokens         int,
  output_tokens        int,
  web_searches         int,
  audio_ms             bigint,
  estimated_usd        numeric(12,6),
  actual_usd           numeric(12,6),
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);

CREATE TABLE cost_reservations (          -- 비용 예약 장부 (PER-003)
  -- 공통
  job_id               bigint,
  recording_session_id bigint,
  utc_date             date NOT NULL,
  reserved_usd         numeric(12,6) NOT NULL,
  settled_usd          numeric(12,6),
  status               text NOT NULL DEFAULT 'held' CHECK (status IN ('held','settled','released')),
  settled_at           timestamptz,
  CHECK (num_nonnulls(job_id, recording_session_id) = 1),
  FOREIGN KEY (user_id) REFERENCES users ON DELETE CASCADE
);
CREATE INDEX ON cost_reservations (utc_date);
CREATE INDEX ON cost_reservations (user_id) WHERE status = 'held';
-- 사용자 하루 사용액 = 그날 settled 합 + 날짜와 상관없이 held 합 (예약은 날짜가 바뀌어도 풀리지 않는다).
-- 전체 한도는 platform.global_spend()로 보고, 예약 트랜잭션은 pg_advisory_xact_lock으로 직렬화한다.
-- 작업을 끝내는 트랜잭션(성공·실패·취소·인계 상한 초과)에서 그 작업의 held 행을 settled나 released로 바꾼다. 남으면 한도를 계속 잡는다.
```

**계정 용량** (PER-003 6): 살아 있는 `audio_chunks.bytes` 합 + 진행 중 녹음의 예상 용량. 텍스트는 처음엔 세지 않는다. 음성에 비해 작아서다.

## 9. 결정 항목

추천안을 위 DDL에 반영해 두었다. 다르게 정하면 해당 부분을 고친다. 2026-11-17에 D1~D9를 확정했다. D6·D8은 요구사항 v0.4.3 개정으로 이어졌다. 2026-11-18에 D7·D9를 고치고 D10·D11을 더했다.

| # | 결정 | 추천 | 대안과 비용 |
|---|---|---|---|
| D1 | 블록 ID (**확정**, [ADR-0013](adr/0013-client-generated-block-uuid.md)) | 편집기가 만드는 uuid(v7) | 서버 bigint. 편집기가 새 블록에 임시 ID를 쓰고 저장 뒤 바꿔 끼워야 한다 |
| D2 | 휴지통 숨김 (**확정**, [ADR-0011](adr/0011-trash-batch-id-hidden-by-rls.md)) | RLS RESTRICTIVE 정책으로 DB가 숨김 | 모든 쿼리에 `deletion_batch_id IS NULL`. 하나만 빠뜨려도 DAR-006 1 위반 |
| D3 | 갱신 필요·출처 삭제됨 (**확정**, [ADR-0012](adr/0012-derived-citation-status.md)) | 버전 비교로 계산(4.1) | 상태 열 저장. 근거가 바뀔 때마다 퍼뜨리는 작업이 필요하다 |
| D4 | 사용자 편집 버전 (**확정**) | 저장할 때마다 새 리비전·새 노트 버전. 이력 화면이 시간으로 묶어 보여 준다 | 편집 세션 단위로 묶기. 행은 줄지만 '저장됨'(SFR-009 1)과 바꾸지 않는 리비전 규칙이 복잡해진다 |
| D5 | 개념 식별 (**확정**, [ADR-0015](adr/0015-per-course-concepts.md)) | 개념과 이해 상태는 과목마다 따로 둔다. 과목 안에서 정규화 이름 `key`로 묶고, AI가 같은 개념이라 판단하면 `merged_into_id`로 합친다 | 과목을 넘는 개념. 과목 삭제(DAR-006 3) 범위가 모호하고, 같은 이름이 과목마다 다른 뜻일 수 있다 |
| D6 | 실시간 요약 (**확정**) | DB에 두지 않는다. Redis에 강의별로 두고 최종 노트가 발행되면 지운다(SFR-006 6). 강의당 실행 1·대기 1 제한은 `jobs`로 건다 | 별도 `notes` 행. 영구 저장할 이유가 없다 |
| D7 | 블록 내용 형식 (**확정**, [ADR-0020](adr/0020-tiptap-flat-blocks-with-depth.md)) | `jsonb`. 자식을 뺀 Tiptap 노드 JSON 하나. 블록 트리는 `note_versions.depths`로 | Markdown `text`. 편집기와 오갈 때마다 변환해야 한다 |
| D8 | 전사 구간 단위 (**확정**, [ADR-0014](adr/0014-utterance-transcript-segments.md)) | 닫힌 발화 하나 = 행 하나. 발화 종료 신호, 15초 상한, 일시정지·종료·STT 세션 교체 때 닫고 그 뒤로 바꾸지 않는다(요구사항 v0.4.3 SFR-004 3)) | 1초 묶음마다 한 행. 문장이 아무 데서나 잘려 정정·수정 제안이 여러 행에 걸친다 |
| D9 | LangGraph 체크포인트 (**2026-11-19 변경**, [ADR-0023](adr/0023-course-update-checkpointer-and-interrupt.md)) | Q&A는 체크포인터 없이 메모리에서만(SER-001 4). 과목 노트 업데이트는 Postgres 체크포인터(`langgraph` 스키마, `thread_id = note_updates.id`)로 재개하고, 의미 충돌은 `interrupt`로 사용자 확인. 이중 반영은 반영 노드가 `status = 'completed'`와 함께 커밋해 막는다 | 체크포인터 없이 `note_updates.completed_stages`로 재개(2026-11-18안). 사용자 확인을 그래프 밖에서 이어 붙여야 하고, 단원 경계와 단원별 완료 기록을 따로 저장해야 한다 |
| D10 | 작업 실행 기록 (**확정**, [ADR-0017](adr/0017-taskiq-delivery-sdk-retries.md)~[0019](adr/0019-outbox-and-ack-after-commit.md)) | `jobs.attempt_no`(늦은 실행 차단), Redis lease(실행 중 여부), `outbox`(전달·중요 이벤트), `jobs (user_id, idempotency_key)` | lease를 DB에(heartbeat가 DB 쓰기), `jobs`에 전송 시각 열(작업 전달과 이벤트가 다른 경로) |
| D11 | Q&A 후속 처리 (**2026-11-18**, [ADR-0022](adr/0022-qa-followup-stages-in-one-job.md)) | `qa_answer` 작업 하나가 답변 → 반영 → 관찰 단계를 순서대로 한다. 완료 표시는 `messages.answer_status`·`reflect_status`·`learner_status`. 계정 한도는 사용자가 시작한 작업에만 | 반영·관찰을 별도 작업으로. 답변 뒤 Q&A 한도를 바로 반납하지만 실행 허가·대기열·자리 이어받기를 새로 만들어야 한다 |

## 10. 확인된 위험

- **ID 재사용과 삭제 기록**: 옛 백업을 복원하면 시퀀스도 그 시점으로 돌아간다. 복원 뒤 새 행이 이미 삭제 기록에 있는 ID를 받으면, 다음 복원 때 삭제 기록 재적용이 그 새 행을 지운다. 복원 절차에 "모든 시퀀스를 S3 삭제 기록의 최대 ID보다 크게 올린다"를 넣는다.
- **STT 원본 삭제도 삭제다**: 7일 뒤 `stt_text`를 비우는 것도 S3 삭제 기록에 남겨야 백업 복원 때 원본이 되살아나지 않는다(DAR-007 4).
- **세션·로그인 조회의 RLS 예외**: 1.4의 `SECURITY DEFINER` 함수 넷이 RLS의 유일한 구멍이다. 출시 차단 RLS 테스트(architecture 8장)에 이 함수들을 넣는다.

## 11. 요구사항 연결

| 요구사항 | 테이블·제약 |
|---|---|
| SFR-001 | `context_versions`, `recording_sessions.context_version_id`, `stt_sessions.context_version_id` |
| SFR-002·003 | `recording_sessions`, `one_active_recording`, `recording_gaps(kind='pause')` |
| SFR-004 | `transcript_segments` (`close_reason`, `closed_at`·`committed_at`, `maybe_duplicate`), `recording_gaps(kind='missing')` |
| SFR-006 | DB 없음(Redis). 작업 제한만 `one_live_summary_*` |
| SFR-007·015 | `notes`, `note_versions` |
| SFR-008 | `note_updates` (`id` = 체크포인트 thread), `notes.locked_until`, `note_changes(origin='course_update')`, `langgraph` 체크포인트 |
| SFR-009·010·022 | `block_revisions.author`·`reason`, `note_versions` (`depths`), `citations`, `note_changes(origin='lecture_regen')` |
| SFR-013·048, DAR-006 | `deletion_batches`, `deletion_batch_id`, `hide_trash` 정책 |
| SFR-016·021 | `messages` (`answer_status`·`reflect_status`·`learner_status` 단계 완료 표시), `citations(message_id)` |
| SFR-017~020·049 | `messages.reflect_*`, `note_changes` |
| SFR-023·047, DAR-005 | `search_entries` (`body` pg_bigm, `embedding` pgvector), 4.1 계산 |
| SFR-024~027, DAR-003 | `observations`, `concept_states`, `gradings.cause` |
| SFR-028~042·052·053, DAR-004 | `review_units`, `review_items`, `review_item_versions`, `attempts`, `gradings`, `review_logs`, `schedule_events`, `answer_drafts`, `email_digests` |
| SFR-044·045 | `auth_sessions`, `users.status`·`generation` |
| SFR-046·058 | `segment_corrections`, `correction_suggestions`, `term_candidates`, `stt_text_purge_at` |
| DAR-001 | `audio_chunks`, `recording_sessions.audio_expires_at`·`last_audio_saved_at` |
| SER-001 | 원문은 `messages.content`에만. `jobs.payload`·`observations`에 원문 열 없음 |
| SER-002 | 복합 FK(1.3), RLS(1.4) |
| PER-003 | `cost_reservations`, `ai_calls`, `one_qa`, 작업 등록 잠금(사용자가 시작한 작업) |
| QUR-002 | `notes.locked_until`, `generation`, `jobs.attempt_no` |
| QUR-004 | `jobs.attempt_no`, `jobs (user_id, idempotency_key)`, `outbox`, `observations.dedupe_key`, `review_logs.grading_id` |
| QUR-007 | `jobs`, `job_stages`, `ai_calls` |
| COR-004·005 | `consents` |
