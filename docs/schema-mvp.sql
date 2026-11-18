-- Notree MVP 스키마 (테이블 18개). 설계 노트: docs/schema-mvp.md
-- 핵심 흐름만 담는다: 녹음·전사 → 노트 → Q&A로 노트 보완 → 이해 상태에 맞춘 복습.
-- 테이블·FK·인덱스·논리명(COMMENT)만 있다. RLS·권한은 schema-mvp-security.sql을 이 파일 다음에 실행한다.
-- 규칙 (postgres-patterns 스킬): ID bigint identity · text · timestamptz · 상태값 text + CHECK · FK마다 인덱스
--   블록 ID만 편집기가 만드는 UUIDv7이다 (ADR-0013)
--   금액은 numeric(10,6): AI 호출 한 건이 1센트보다 작다
-- 삭제: 과목·강의·노트·대화는 deleted_at으로 숨기고 3주 뒤 cron이 지운다. 자식은 부모를 거쳐서만 조회한다.

-- ─── 계정 ──────────────────────────────────────────────────────

CREATE TABLE users (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  google_sub           text NOT NULL UNIQUE,
  email                text NOT NULL,
  status               text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'withdrawing')),
  withdraw_at          timestamptz,
  recording_consent_at timestamptz,
  ai_consent_at        timestamptz,
  daily_minutes        int NOT NULL DEFAULT 20 CHECK (daily_minutes > 0),
  created_at           timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'withdrawing') = (withdraw_at IS NOT NULL))
);

CREATE TABLE sessions (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  token_hash bytea NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX sessions_user ON sessions (user_id);

-- ─── 강의 기록 ─────────────────────────────────────────────────

CREATE TABLE courses (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  name       text NOT NULL,
  background text NOT NULL DEFAULT '',
  terms      text[] NOT NULL DEFAULT '{}' CHECK (cardinality(terms) <= 200),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX courses_user ON courses (user_id, created_at);

CREATE TABLE lectures (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL,
  course_id  bigint NOT NULL REFERENCES courses ON DELETE CASCADE,
  title      text NOT NULL,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX lectures_course ON lectures (course_id, created_at);

CREATE TABLE recordings (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id          bigint NOT NULL,
  lecture_id       bigint NOT NULL REFERENCES lectures ON DELETE CASCADE,
  status           text NOT NULL CHECK (status IN ('recording', 'paused', 'completed', 'failed')),
  context          jsonb NOT NULL,              -- 시작 시점의 {background, terms} 고정본 (SFR-001 2)
  started_at       timestamptz NOT NULL,
  ended_at         timestamptz,
  audio_bytes      bigint NOT NULL DEFAULT 0,   -- 음성 파일은 S3. 계정 용량 계산용
  audio_expires_at timestamptz,                 -- 종료 + 7일
  created_at       timestamptz NOT NULL DEFAULT now(),
  CHECK ((ended_at IS NULL) = (audio_expires_at IS NULL))
);
CREATE UNIQUE INDEX recordings_one_active ON recordings (user_id) WHERE status IN ('recording', 'paused');
CREATE INDEX recordings_lecture ON recordings (lecture_id, started_at);
CREATE INDEX recordings_audio_expiry ON recordings (audio_expires_at) WHERE audio_bytes > 0;

CREATE TABLE segments (
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id        bigint NOT NULL,
  recording_id   bigint NOT NULL REFERENCES recordings ON DELETE CASCADE,
  start_ms       int NOT NULL,
  end_ms         int NOT NULL,
  stt_text       text NOT NULL,
  corrected_text text,                          -- 사용자 정정. NULL이면 STT 원문이 기준
  created_at     timestamptz NOT NULL DEFAULT now(),
  CHECK (end_ms >= start_ms)
);
CREATE INDEX segments_timeline ON segments (recording_id, start_ms);

-- ─── 노트 ──────────────────────────────────────────────────────

CREATE TABLE notes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL,
  kind       text NOT NULL CHECK (kind IN ('lecture', 'course')),
  course_id  bigint UNIQUE REFERENCES courses ON DELETE CASCADE,    -- 과목 노트는 과목당 1개
  lecture_id bigint UNIQUE REFERENCES lectures ON DELETE CASCADE,   -- 강의 노트는 강의당 1개
  status     text NOT NULL DEFAULT 'generating' CHECK (status IN ('generating', 'completed', 'partial', 'failed')),
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((kind = 'course') = (course_id IS NOT NULL)),
  CHECK ((kind = 'course') = (lecture_id IS NULL))
);

CREATE TABLE note_blocks (
  id         uuid PRIMARY KEY CHECK (uuid_extract_version(id) = 7),   -- 편집기가 만든다. AI 블록은 서버가 만든다 (ADR-0013)
  user_id    bigint NOT NULL,
  note_id    bigint NOT NULL REFERENCES notes ON DELETE CASCADE,
  position   double precision NOT NULL,         -- 두 블록 사이에 끼우면 중간값
  depth      smallint NOT NULL DEFAULT 0 CHECK (depth >= 0),   -- 들여쓰기. 앞 블록보다 최대 1 깊다(서버가 검사, ADR-0020)
  kind       text NOT NULL CHECK (kind IN ('paragraph', 'heading', 'list_item', 'code', 'table', 'supplement')),
  content    jsonb NOT NULL,
  author     text NOT NULL CHECK (author IN ('ai', 'user', 'qa')),
  sources    jsonb NOT NULL DEFAULT '[]',       -- 근거 [{segment_id} | {block_id} | {url}]
  revision   int NOT NULL DEFAULT 1,            -- 저장할 때 +1. 편집 충돌 확인 (QUR-002)
  deleted_at timestamptz,                       -- 이력과 되돌리기를 위해 행은 남긴다
  updated_at timestamptz NOT NULL DEFAULT now(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX note_blocks_note ON note_blocks (note_id, position);

-- ─── 질의응답 ──────────────────────────────────────────────────

CREATE TABLE conversations (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL,
  course_id  bigint NOT NULL REFERENCES courses ON DELETE CASCADE,
  title      text,
  deleted_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX conversations_course ON conversations (course_id, created_at);

CREATE TABLE messages (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         bigint NOT NULL,
  conversation_id bigint NOT NULL REFERENCES conversations ON DELETE CASCADE,
  role            text NOT NULL CHECK (role IN ('user', 'assistant')),
  content         text,
  answer_status   text CHECK (answer_status IN ('generating', 'completed', 'interrupted', 'failed',
                                                'evidence_changed')),   -- evidence_changed: 저장 직전 근거가 바뀜, 질문 보존 (SFR-016 8, ADR-0006)
  sources         jsonb NOT NULL DEFAULT '[]',
  reflect_status  text CHECK (reflect_status IN ('not_needed', 'applied', 'pending', 'held', 'failed')),   -- 노트 반영 결과 (SFR-021)
  reflect_reason  text CHECK (char_length(reflect_reason) <= 300),   -- 반영 판단 이유, 2문장 이내 (SFR-017 3)
  learner_status  text CHECK (learner_status IN ('not_needed', 'applied', 'pending', 'held', 'failed')),   -- 학습 상태 갱신 결과 = 관찰 추가와 이해 상태 재계산 (SFR-021). held를 언제 쓰는지는 미정(learner 담당)
  answer_kind     text CHECK (answer_kind IN ('answer', 'clarification', 'conflict')),   -- 답변 종류: 답변 · 확인 질문 · 상충 안내
  truncated       boolean NOT NULL DEFAULT false,   -- 맥락 자료나 출력을 잘랐음. 화면에 표시한다 (PER-004 4)
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK (role = 'assistant' OR (answer_status IS NULL AND content IS NOT NULL)),
  CHECK (role = 'user' OR answer_status IS NOT NULL),
  CHECK (role = 'user' OR answer_status = 'completed' OR content IS NULL),   -- 미완성 답변 본문은 저장하지 않는다 (SFR-021 3)
  CHECK (role = 'assistant' OR answer_kind IS NULL),
  CHECK (answer_status IS DISTINCT FROM 'completed' OR answer_kind IS NOT NULL)
);
CREATE INDEX messages_page ON messages (conversation_id, id);
-- answer_status·reflect_status·learner_status는 qa_answer 작업의 단계 완료 표시다 (ADR-0022). 각 단계 결과와 같은 트랜잭션에서 쓰고,
-- 재시도 때 이 값을 보고 남은 단계만 한다. 반영·관찰 단계는 answer_status = 'completed'이고 answer_kind = 'answer'일 때만 돈다.
-- 확인 질문·상충 안내는 답변 저장 트랜잭션에서 reflect_status·learner_status를 'not_needed'로 쓴다.

CREATE TABLE note_changes (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL,
  note_id    bigint NOT NULL REFERENCES notes ON DELETE CASCADE,
  message_id bigint REFERENCES messages ON DELETE SET NULL,      -- 대화를 지워도 반영 기록은 남는다
  block_id   uuid REFERENCES note_blocks ON DELETE SET NULL,     -- 대상 블록. 추가면 반영 뒤 새 블록
  op         text NOT NULL CHECK (op IN ('add', 'modify', 'supplement', 'delete')),
  proposal   jsonb NOT NULL,
  status     text NOT NULL CHECK (status IN ('pending', 'applied', 'rejected', 'reverted', 'held')),   -- pending = 확인 필요
  reason     text CHECK (char_length(reason) <= 300),
  applied_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK ((status IN ('applied', 'reverted')) = (applied_at IS NOT NULL))
);
CREATE INDEX note_changes_note ON note_changes (note_id, created_at);
CREATE INDEX note_changes_message ON note_changes (message_id) WHERE message_id IS NOT NULL;
CREATE INDEX note_changes_block ON note_changes (block_id) WHERE block_id IS NOT NULL;

CREATE TABLE block_revisions (                   -- 블록이 바뀔 때마다 한 행. 바꾸지 않는다
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL,
  block_id   uuid NOT NULL REFERENCES note_blocks ON DELETE CASCADE,
  revision   int NOT NULL,
  content    jsonb,                              -- NULL이면 이 판에서 삭제됨
  author     text NOT NULL CHECK (author IN ('ai', 'user', 'qa')),
  change_id  bigint REFERENCES note_changes ON DELETE SET NULL,   -- Q&A 반영·되돌리기로 바뀐 판
  reason     text,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (block_id, revision)
);
CREATE INDEX block_revisions_change ON block_revisions (change_id) WHERE change_id IS NOT NULL;

-- ─── 학습자 상태 ───────────────────────────────────────────────

CREATE TABLE concepts (
  id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id          bigint NOT NULL,
  course_id        bigint NOT NULL REFERENCES courses ON DELETE CASCADE,
  name             text NOT NULL,
  key              text NOT NULL,               -- 정규화한 이름. UPSERT 대상
  state            text NOT NULL DEFAULT 'unassessed' CHECK (state IN ('unassessed', 'learning', 'confirmed', 'recheck')),
  state_updated_at timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_id, key)
);

-- ─── 복습 ──────────────────────────────────────────────────────

CREATE TABLE review_cards (                      -- 문제 하나와 그 FSRS 일정
  id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id        bigint NOT NULL,
  concept_id     bigint NOT NULL REFERENCES concepts ON DELETE CASCADE,
  item_type      text NOT NULL CHECK (item_type IN ('essay', 'short', 'mcq', 'flashcard')),
  prompt         jsonb NOT NULL,
  answer         jsonb NOT NULL,
  rubric         jsonb NOT NULL,
  sources        jsonb NOT NULL DEFAULT '[]',   -- 근거 블록. 블록이 바뀌면 paused (SFR-041)
  status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'retired')),
  fsrs_state     text NOT NULL DEFAULT 'new' CHECK (fsrs_state IN ('new', 'learning', 'review', 'relearning')),
  stability      double precision,
  difficulty     double precision,
  reps           int NOT NULL DEFAULT 0,
  lapses         int NOT NULL DEFAULT 0,
  due_at         timestamptz,                   -- 연기·건너뜀도 이 값을 미룬다
  last_review_at timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX review_cards_due ON review_cards (user_id, due_at) WHERE status = 'active';
CREATE INDEX review_cards_concept ON review_cards (concept_id);

CREATE TABLE attempts (                          -- 제출 답안과 평가
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id         bigint NOT NULL,
  card_id         bigint NOT NULL REFERENCES review_cards ON DELETE CASCADE,
  answer          text,                         -- 플래시카드는 NULL
  hint_used       boolean NOT NULL DEFAULT false,
  self_rating     text CHECK (self_rating IN ('again', 'hard', 'good', 'easy')),
  idempotency_key uuid NOT NULL UNIQUE,         -- 재전송 방지 (QUR-004)
  grade_status    text NOT NULL DEFAULT 'pending' CHECK (grade_status IN ('pending', 'completed', 'failed')),
  rating          text CHECK (rating IN ('again', 'hard', 'good', 'easy')),   -- FSRS에 반영한 등급
  feedback        jsonb,
  presented_at    timestamptz NOT NULL,
  graded_at       timestamptz,
  created_at      timestamptz NOT NULL DEFAULT now(),
  CHECK ((grade_status = 'completed') = (rating IS NOT NULL AND graded_at IS NOT NULL))
);
CREATE INDEX attempts_card ON attempts (card_id, created_at);

CREATE TABLE observations (                      -- 이해 상태의 근거. 원문 없이 증거만, 바꾸지 않는다 (DAR-003)
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     bigint NOT NULL,
  concept_id  bigint NOT NULL REFERENCES concepts ON DELETE CASCADE,
  attempt_id  bigint REFERENCES attempts ON DELETE CASCADE,   -- 복습에서 나온 관찰
  message_id  bigint REFERENCES messages ON DELETE CASCADE,   -- Q&A에서 나온 관찰
  kind        text NOT NULL CHECK (kind IN ('success', 'partial', 'failure', 'misconception', 'confusion')),
  strength    text NOT NULL CHECK (strength IN ('strong', 'weak')),
  hint_used   boolean NOT NULL DEFAULT false,
  observed_at timestamptz NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (concept_id, attempt_id),             -- 같은 답안을 두 번 반영하지 않는다
  UNIQUE (concept_id, message_id),
  CHECK (num_nonnulls(attempt_id, message_id) = 1),
  CHECK (message_id IS NULL OR strength = 'weak')   -- Q&A 관찰은 약한 근거 (SFR-025 4)
);
CREATE INDEX observations_concept ON observations (concept_id, observed_at);
CREATE INDEX observations_attempt ON observations (attempt_id) WHERE attempt_id IS NOT NULL;
CREATE INDEX observations_message ON observations (message_id) WHERE message_id IS NOT NULL;

-- ─── 운영 ──────────────────────────────────────────────────────

-- 작업 상태의 원본 (ADR-0001). Redis 메시지에는 작업 ID와 user_id만 싣는다.
-- 이 표도 RLS를 받으므로 워커는 메시지의 user_id로 SET LOCAL app.user_id를 한 뒤에야 행을 읽는다.
CREATE TABLE jobs (
  id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id     bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  -- final_note: 강의 최종 노트 생성 (SFR-007)
  -- course_update: 과목 노트 업데이트 (SFR-008)
  -- qa_answer: Q&A 답변 → 노트 반영 → 관찰 단계 (ADR-0022)
  -- generate_card: 복습 카드 출제 (SFR-034)
  -- grade: 답안 채점과 관찰 추가 (SFR-035)
  -- purge: 보관 기간이 지난 데이터 영구 삭제
  kind        text NOT NULL CHECK (kind IN ('final_note', 'course_update', 'qa_answer',
                                            'generate_card', 'grade', 'purge')),
  status      text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
  target_id   bigint,                           -- kind에 따라 강의·노트·메시지·답안 ID
  payload     jsonb NOT NULL DEFAULT '{}',      -- ID만. 질문 원문 금지 (SER-001)
  attempt     int NOT NULL DEFAULT 0 CHECK (attempt BETWEEN 0 AND 4),
  error_code  text,
  run_after   timestamptz NOT NULL DEFAULT now(),
  started_at  timestamptz,
  finished_at timestamptz,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_user ON jobs (user_id, created_at);
-- shortcut: 여러 사용자를 훑는 회수 조회는 notree_app으로 못 한다(RLS), 회수 루프를 만들 때 SECURITY DEFINER 함수를 추가한다 (ADR-0010)
CREATE INDEX jobs_ready ON jobs (run_after) WHERE status = 'queued';   -- FOR UPDATE SKIP LOCKED

-- 작업 전달을 jobs와 같은 트랜잭션에 적어 둔다 (ADR-0019). 커밋 직후 보내고 sent_at을 채운다.
-- 회수 루프가 sent_at IS NULL인 오래된 행을 다시 보낸다. 받는 쪽은 jobs.status = 'queued'로 중복을 거른다.
-- shortcut: 작업 전달만 싣는다, 완료 이벤트를 잃는 것이 문제가 되면 kind 열을 더해 같은 표에 얹는다
CREATE TABLE outbox (
  id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id    bigint NOT NULL,
  job_id     bigint NOT NULL REFERENCES jobs ON DELETE CASCADE,
  sent_at    timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outbox_unsent ON outbox (created_at) WHERE sent_at IS NULL;   -- 회수 루프

CREATE TABLE usage_ledger (                      -- AI 비용 예약과 정산 (PER-003)
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id      bigint NOT NULL REFERENCES users ON DELETE CASCADE,
  job_id       bigint REFERENCES jobs ON DELETE SET NULL,
  provider     text NOT NULL CHECK (provider IN ('openai', 'soniox')),
  utc_date     date NOT NULL,
  reserved_usd numeric(10,6) NOT NULL CHECK (reserved_usd >= 0),
  cost_usd     numeric(10,6) CHECK (cost_usd >= 0),
  status       text NOT NULL DEFAULT 'held' CHECK (status IN ('held', 'settled', 'released')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  CHECK ((status = 'settled') = (cost_usd IS NOT NULL))
);
CREATE INDEX usage_user_day ON usage_ledger (user_id, utc_date);
CREATE INDEX usage_job ON usage_ledger (job_id) WHERE job_id IS NOT NULL;

-- ─── 논리 이름 (ERD 도구의 논리 뷰. 용어는 GLOSSARY.md) ─────────

COMMENT ON TABLE users IS '사용자';
COMMENT ON COLUMN users.id IS '사용자 ID';
COMMENT ON COLUMN users.google_sub IS '구글 계정 식별자';
COMMENT ON COLUMN users.email IS '이메일';
COMMENT ON COLUMN users.status IS '계정 상태';
COMMENT ON COLUMN users.withdraw_at IS '탈퇴 요청 시각';
COMMENT ON COLUMN users.recording_consent_at IS '녹음 허락 확인 시각';
COMMENT ON COLUMN users.ai_consent_at IS '외부 AI 처리 동의 시각';
COMMENT ON COLUMN users.daily_minutes IS '하루 학습 가능 시간(분)';
COMMENT ON COLUMN users.created_at IS '생성 시각';

COMMENT ON TABLE sessions IS '로그인 세션';
COMMENT ON COLUMN sessions.id IS '세션 ID';
COMMENT ON COLUMN sessions.user_id IS '사용자 ID';
COMMENT ON COLUMN sessions.token_hash IS '쿠키 해시';
COMMENT ON COLUMN sessions.expires_at IS '만료 시각';
COMMENT ON COLUMN sessions.revoked_at IS '철회 시각';
COMMENT ON COLUMN sessions.created_at IS '생성 시각';

COMMENT ON TABLE courses IS '과목';
COMMENT ON COLUMN courses.id IS '과목 ID';
COMMENT ON COLUMN courses.user_id IS '사용자 ID';
COMMENT ON COLUMN courses.name IS '과목명';
COMMENT ON COLUMN courses.background IS '배경 설명';
COMMENT ON COLUMN courses.terms IS '전문용어 목록';
COMMENT ON COLUMN courses.deleted_at IS '삭제 시각';
COMMENT ON COLUMN courses.created_at IS '생성 시각';

COMMENT ON TABLE lectures IS '강의';
COMMENT ON COLUMN lectures.id IS '강의 ID';
COMMENT ON COLUMN lectures.user_id IS '사용자 ID';
COMMENT ON COLUMN lectures.course_id IS '과목 ID';
COMMENT ON COLUMN lectures.title IS '강의 제목';
COMMENT ON COLUMN lectures.deleted_at IS '삭제 시각';
COMMENT ON COLUMN lectures.created_at IS '생성 시각';

COMMENT ON TABLE recordings IS '녹음 세션';
COMMENT ON COLUMN recordings.id IS '녹음 세션 ID';
COMMENT ON COLUMN recordings.user_id IS '사용자 ID';
COMMENT ON COLUMN recordings.lecture_id IS '강의 ID';
COMMENT ON COLUMN recordings.status IS '녹음 상태';
COMMENT ON COLUMN recordings.context IS '고정한 맥락';
COMMENT ON COLUMN recordings.started_at IS '시작 시각';
COMMENT ON COLUMN recordings.ended_at IS '종료 시각';
COMMENT ON COLUMN recordings.audio_bytes IS '음성 용량(바이트)';
COMMENT ON COLUMN recordings.audio_expires_at IS '음성 만료 시각';
COMMENT ON COLUMN recordings.created_at IS '생성 시각';

COMMENT ON TABLE segments IS '전사 구간';
COMMENT ON COLUMN segments.id IS '전사 구간 ID';
COMMENT ON COLUMN segments.user_id IS '사용자 ID';
COMMENT ON COLUMN segments.recording_id IS '녹음 세션 ID';
COMMENT ON COLUMN segments.start_ms IS '시작 위치(ms)';
COMMENT ON COLUMN segments.end_ms IS '끝 위치(ms)';
COMMENT ON COLUMN segments.stt_text IS 'STT 원문';
COMMENT ON COLUMN segments.corrected_text IS '정정 전사';
COMMENT ON COLUMN segments.created_at IS '생성 시각';

COMMENT ON TABLE notes IS '노트';
COMMENT ON COLUMN notes.id IS '노트 ID';
COMMENT ON COLUMN notes.user_id IS '사용자 ID';
COMMENT ON COLUMN notes.kind IS '노트 종류';
COMMENT ON COLUMN notes.course_id IS '과목 ID';
COMMENT ON COLUMN notes.lecture_id IS '강의 ID';
COMMENT ON COLUMN notes.status IS '생성 상태';
COMMENT ON COLUMN notes.deleted_at IS '삭제 시각';
COMMENT ON COLUMN notes.created_at IS '생성 시각';

COMMENT ON TABLE note_blocks IS '노트 블록';
COMMENT ON COLUMN note_blocks.id IS '블록 ID';
COMMENT ON COLUMN note_blocks.user_id IS '사용자 ID';
COMMENT ON COLUMN note_blocks.note_id IS '노트 ID';
COMMENT ON COLUMN note_blocks.position IS '순서';
COMMENT ON COLUMN note_blocks.depth IS '깊이';
COMMENT ON COLUMN note_blocks.kind IS '블록 종류';
COMMENT ON COLUMN note_blocks.content IS '내용';
COMMENT ON COLUMN note_blocks.author IS '작성 주체';
COMMENT ON COLUMN note_blocks.sources IS '근거';
COMMENT ON COLUMN note_blocks.revision IS '판 번호';
COMMENT ON COLUMN note_blocks.deleted_at IS '삭제 시각';
COMMENT ON COLUMN note_blocks.updated_at IS '수정 시각';
COMMENT ON COLUMN note_blocks.created_at IS '생성 시각';

COMMENT ON TABLE conversations IS '대화';
COMMENT ON COLUMN conversations.id IS '대화 ID';
COMMENT ON COLUMN conversations.user_id IS '사용자 ID';
COMMENT ON COLUMN conversations.course_id IS '과목 ID';
COMMENT ON COLUMN conversations.title IS '대화 제목';
COMMENT ON COLUMN conversations.deleted_at IS '삭제 시각';
COMMENT ON COLUMN conversations.created_at IS '생성 시각';

COMMENT ON TABLE messages IS '대화 메시지';
COMMENT ON COLUMN messages.id IS '메시지 ID';
COMMENT ON COLUMN messages.user_id IS '사용자 ID';
COMMENT ON COLUMN messages.conversation_id IS '대화 ID';
COMMENT ON COLUMN messages.role IS '발화자';
COMMENT ON COLUMN messages.content IS '본문';
COMMENT ON COLUMN messages.answer_status IS '답변 상태';
COMMENT ON COLUMN messages.sources IS '근거';
COMMENT ON COLUMN messages.reflect_status IS '노트 반영 결과';
COMMENT ON COLUMN messages.reflect_reason IS '반영 판단 이유';
COMMENT ON COLUMN messages.learner_status IS '학습 상태 갱신 결과';
COMMENT ON COLUMN messages.answer_kind IS '답변 종류';
COMMENT ON COLUMN messages.truncated IS '잘림 여부';
COMMENT ON COLUMN messages.created_at IS '생성 시각';

COMMENT ON TABLE note_changes IS '노트 변경안';
COMMENT ON COLUMN note_changes.id IS '변경안 ID';
COMMENT ON COLUMN note_changes.user_id IS '사용자 ID';
COMMENT ON COLUMN note_changes.note_id IS '노트 ID';
COMMENT ON COLUMN note_changes.message_id IS '메시지 ID';
COMMENT ON COLUMN note_changes.block_id IS '대상 블록 ID';
COMMENT ON COLUMN note_changes.op IS '변경 종류';
COMMENT ON COLUMN note_changes.proposal IS '변경 내용';
COMMENT ON COLUMN note_changes.status IS '처리 상태';
COMMENT ON COLUMN note_changes.reason IS '변경 이유';
COMMENT ON COLUMN note_changes.applied_at IS '반영 시각';
COMMENT ON COLUMN note_changes.created_at IS '생성 시각';

COMMENT ON TABLE block_revisions IS '블록 이력';
COMMENT ON COLUMN block_revisions.id IS '이력 ID';
COMMENT ON COLUMN block_revisions.user_id IS '사용자 ID';
COMMENT ON COLUMN block_revisions.block_id IS '블록 ID';
COMMENT ON COLUMN block_revisions.revision IS '판 번호';
COMMENT ON COLUMN block_revisions.content IS '내용';
COMMENT ON COLUMN block_revisions.author IS '작성 주체';
COMMENT ON COLUMN block_revisions.change_id IS '변경안 ID';
COMMENT ON COLUMN block_revisions.reason IS '변경 이유';
COMMENT ON COLUMN block_revisions.created_at IS '생성 시각';

COMMENT ON TABLE concepts IS '개념';
COMMENT ON COLUMN concepts.id IS '개념 ID';
COMMENT ON COLUMN concepts.user_id IS '사용자 ID';
COMMENT ON COLUMN concepts.course_id IS '과목 ID';
COMMENT ON COLUMN concepts.name IS '개념명';
COMMENT ON COLUMN concepts.key IS '정규화 이름';
COMMENT ON COLUMN concepts.state IS '이해 상태';
COMMENT ON COLUMN concepts.state_updated_at IS '상태 갱신 시각';
COMMENT ON COLUMN concepts.created_at IS '생성 시각';

COMMENT ON TABLE review_cards IS '복습 카드';
COMMENT ON COLUMN review_cards.id IS '복습 카드 ID';
COMMENT ON COLUMN review_cards.user_id IS '사용자 ID';
COMMENT ON COLUMN review_cards.concept_id IS '개념 ID';
COMMENT ON COLUMN review_cards.item_type IS '문제 유형';
COMMENT ON COLUMN review_cards.prompt IS '문항';
COMMENT ON COLUMN review_cards.answer IS '정답';
COMMENT ON COLUMN review_cards.rubric IS '평가 기준';
COMMENT ON COLUMN review_cards.sources IS '근거';
COMMENT ON COLUMN review_cards.status IS '제공 상태';
COMMENT ON COLUMN review_cards.fsrs_state IS 'FSRS 단계';
COMMENT ON COLUMN review_cards.stability IS '안정도';
COMMENT ON COLUMN review_cards.difficulty IS '난이도';
COMMENT ON COLUMN review_cards.reps IS '복습 횟수';
COMMENT ON COLUMN review_cards.lapses IS '망각 횟수';
COMMENT ON COLUMN review_cards.due_at IS '예정 시각';
COMMENT ON COLUMN review_cards.last_review_at IS '마지막 복습 시각';
COMMENT ON COLUMN review_cards.created_at IS '생성 시각';

COMMENT ON TABLE attempts IS '제출 답안';
COMMENT ON COLUMN attempts.id IS '답안 ID';
COMMENT ON COLUMN attempts.user_id IS '사용자 ID';
COMMENT ON COLUMN attempts.card_id IS '복습 카드 ID';
COMMENT ON COLUMN attempts.answer IS '답안';
COMMENT ON COLUMN attempts.hint_used IS '힌트 사용 여부';
COMMENT ON COLUMN attempts.self_rating IS '자기 평가';
COMMENT ON COLUMN attempts.idempotency_key IS '재전송 방지 키';
COMMENT ON COLUMN attempts.grade_status IS '평가 상태';
COMMENT ON COLUMN attempts.rating IS '반영 등급';
COMMENT ON COLUMN attempts.feedback IS '피드백';
COMMENT ON COLUMN attempts.presented_at IS '제공 시각';
COMMENT ON COLUMN attempts.graded_at IS '평가 시각';
COMMENT ON COLUMN attempts.created_at IS '제출 시각';

COMMENT ON TABLE observations IS '관찰';
COMMENT ON COLUMN observations.id IS '관찰 ID';
COMMENT ON COLUMN observations.user_id IS '사용자 ID';
COMMENT ON COLUMN observations.concept_id IS '개념 ID';
COMMENT ON COLUMN observations.attempt_id IS '답안 ID';
COMMENT ON COLUMN observations.message_id IS '메시지 ID';
COMMENT ON COLUMN observations.kind IS '관찰 종류';
COMMENT ON COLUMN observations.strength IS '근거 강도';
COMMENT ON COLUMN observations.hint_used IS '힌트 사용 여부';
COMMENT ON COLUMN observations.observed_at IS '관찰 시각';
COMMENT ON COLUMN observations.created_at IS '생성 시각';

COMMENT ON TABLE jobs IS '작업';
COMMENT ON COLUMN jobs.id IS '작업 ID';
COMMENT ON COLUMN jobs.user_id IS '사용자 ID';
COMMENT ON COLUMN jobs.kind IS '작업 종류';
COMMENT ON COLUMN jobs.status IS '작업 상태';
COMMENT ON COLUMN jobs.target_id IS '대상 ID';
COMMENT ON COLUMN jobs.payload IS '작업 입력';
COMMENT ON COLUMN jobs.attempt IS '시도 횟수';
COMMENT ON COLUMN jobs.error_code IS '오류 코드';
COMMENT ON COLUMN jobs.run_after IS '실행 가능 시각';
COMMENT ON COLUMN jobs.started_at IS '시작 시각';
COMMENT ON COLUMN jobs.finished_at IS '종료 시각';
COMMENT ON COLUMN jobs.created_at IS '생성 시각';

COMMENT ON TABLE outbox IS '보낼 작업';
COMMENT ON COLUMN outbox.id IS '전달 ID';
COMMENT ON COLUMN outbox.user_id IS '사용자 ID';
COMMENT ON COLUMN outbox.job_id IS '작업 ID';
COMMENT ON COLUMN outbox.sent_at IS '전송 시각';
COMMENT ON COLUMN outbox.created_at IS '생성 시각';

COMMENT ON TABLE usage_ledger IS '비용 장부';
COMMENT ON COLUMN usage_ledger.id IS '장부 ID';
COMMENT ON COLUMN usage_ledger.user_id IS '사용자 ID';
COMMENT ON COLUMN usage_ledger.job_id IS '작업 ID';
COMMENT ON COLUMN usage_ledger.provider IS '제공사';
COMMENT ON COLUMN usage_ledger.utc_date IS '사용일(UTC)';
COMMENT ON COLUMN usage_ledger.reserved_usd IS '예약 금액(USD)';
COMMENT ON COLUMN usage_ledger.cost_usd IS '정산 금액(USD)';
COMMENT ON COLUMN usage_ledger.status IS '정산 상태';
COMMENT ON COLUMN usage_ledger.created_at IS '생성 시각';
