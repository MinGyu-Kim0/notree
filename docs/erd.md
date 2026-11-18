<!-- 2026-11-17 스키마(테이블 42개)를 실제 DB에 적용해 카탈로그에서 생성했다. 생성 스크립트는 남기지 않았다. 스키마를 바꾸면 이 그림도 다시 만든다. -->
<!-- 2026-11-18 손으로 고침: note_versions.depths, note_updates.completed_stages, note_changes.job_id, jobs(attempt_no·request_hash, heartbeat_at 제거), outbox 추가. 다음에 DB에서 다시 생성할 때 대조한다. -->

# Notree ERD

[schema.md](schema.md) 설계를 적용한 DB에서 생성했다. 테이블 43개(2026-11-17 생성 42개 + `outbox`), FK 115개(생성 당시 기준).

- 모든 사용자 테이블은 `user_id`로 `users`에 속하고, 부모 참조는 `(user_id, parent_id)` 복합 FK다(ADR-0010). 선은 `user_id`를 뺀 열 이름으로 표시한다.
- `deletion_batch_id`가 있는 테이블은 모두 `deletion_batches`를 참조한다(ADR-0011).
- 위 두 관계는 선이 너무 많아져서 그리지 않는다. 다른 모듈의 테이블은 열 없이 이름만 보인다.
- 선: 부모 쪽 `||`는 반드시 있음(NOT NULL FK), `|o`는 없을 수 있음(NULL 허용 FK). 자식 쪽 `o{`는 0개 이상.

## account

```mermaid
erDiagram
  users {
    bigint id PK
    text google_sub UK
    text email
    text display_name
    text status
    timestamptz withdraw_requested_at
    timestamptz purge_at
    int generation
    timestamptz created_at
  }
  auth_sessions {
    bigint id PK
    bigint user_id
    bytea token_hash UK
    timestamptz last_seen_at
    timestamptz expires_at
    timestamptz revoked_at
    text revoke_reason
    timestamptz created_at
  }
  consents {
    bigint id PK
    bigint user_id
    text kind
    text notice_version
    timestamptz withdrawn_at
    timestamptz created_at
  }
  user_settings {
    bigint user_id PK
    int daily_minutes
    int daily_new
    int daily_reviews
    boolean review_email
  }
```

## capture

```mermaid
erDiagram
  courses {
    bigint id PK
    bigint user_id
    text name
    int last_reserved_minutes
    int generation
    bigint deletion_batch_id
    timestamptz created_at
  }
  context_versions {
    bigint id PK
    bigint user_id
    bigint course_id FK
    int version_no
    text background
    text_array terms
    timestamptz created_at
  }
  lectures {
    bigint id PK
    bigint user_id
    bigint course_id FK
    text title
    int generation
    bigint deletion_batch_id
    timestamptz created_at
  }
  recording_sessions {
    bigint id PK
    bigint user_id
    bigint lecture_id FK
    int seq
    bigint context_version_id FK
    text status
    int reserved_minutes
    timestamptz started_at
    timestamptz ended_at
    text end_reason
    timestamptz audio_expires_at
    timestamptz last_audio_saved_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  stt_sessions {
    bigint id PK
    bigint user_id
    bigint recording_session_id FK
    bigint context_version_id FK
    timestamptz opened_at
    timestamptz closed_at
    text close_reason
    bigint deletion_batch_id
    timestamptz created_at
  }
  transcript_segments {
    bigint id PK
    bigint user_id
    bigint lecture_id FK
    bigint recording_session_id FK
    bigint stt_session_id FK
    int start_ms
    int end_ms
    text stt_text
    timestamptz stt_text_purge_at
    boolean maybe_duplicate
    text close_reason
    timestamptz closed_at
    timestamptz committed_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  segment_corrections {
    bigint id PK
    bigint user_id
    bigint segment_id FK
    text text
    bigint suggestion_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  correction_suggestions {
    bigint id PK
    bigint user_id
    bigint lecture_id FK
    bigint segment_id FK
    bigint note_version_id FK
    text original_text
    text suggested_text
    text reason
    text status
    timestamptz resolved_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  term_candidates {
    bigint id PK
    bigint user_id
    bigint course_id FK
    bigint correction_id FK
    text term
    text status
    bigint deletion_batch_id
    timestamptz created_at
  }
  audio_chunks {
    bigint id PK
    bigint user_id
    bigint recording_session_id FK
    int seq
    int start_ms
    int duration_ms
    text s3_key UK
    int bytes
    timestamptz saved_at
    text source
    bigint deletion_batch_id
    timestamptz created_at
  }
  recording_gaps {
    bigint id PK
    bigint user_id
    bigint recording_session_id FK
    text kind
    int start_ms
    int end_ms
    text cause
    boolean has_audio
    timestamptz retranscribed_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  ai_calls {
  }
  citations {
  }
  concepts {
  }
  conversations {
  }
  cost_reservations {
  }
  note_versions {
  }
  notes {
  }
  search_entries {
  }
  recording_sessions |o--o{ ai_calls : "recording_session_id"
  recording_sessions ||--o{ audio_chunks : "recording_session_id"
  transcript_segments |o--o{ citations : "segment_id"
  courses ||--o{ concepts : "course_id"
  courses ||--o{ context_versions : "course_id"
  courses ||--o{ conversations : "course_id"
  lectures ||--o{ correction_suggestions : "lecture_id"
  note_versions ||--o{ correction_suggestions : "note_version_id"
  transcript_segments ||--o{ correction_suggestions : "segment_id"
  recording_sessions |o--o{ cost_reservations : "recording_session_id"
  courses ||--o{ lectures : "course_id"
  courses |o--o{ notes : "course_id"
  lectures |o--o{ notes : "lecture_id"
  recording_sessions ||--o{ recording_gaps : "recording_session_id"
  context_versions ||--o{ recording_sessions : "context_version_id"
  lectures ||--o{ recording_sessions : "lecture_id"
  courses ||--o{ search_entries : "course_id"
  lectures |o--o{ search_entries : "lecture_id"
  transcript_segments |o--o{ search_entries : "segment_id"
  correction_suggestions |o--o{ segment_corrections : "suggestion_id"
  transcript_segments ||--o{ segment_corrections : "segment_id"
  context_versions ||--o{ stt_sessions : "context_version_id"
  recording_sessions ||--o{ stt_sessions : "recording_session_id"
  courses ||--o{ term_candidates : "course_id"
  segment_corrections ||--o{ term_candidates : "correction_id"
  lectures ||--o{ transcript_segments : "lecture_id"
  recording_sessions ||--o{ transcript_segments : "recording_session_id"
  stt_sessions ||--o{ transcript_segments : "stt_session_id"
```

## notebook

```mermaid
erDiagram
  notes {
    bigint id PK
    bigint user_id
    text kind
    bigint course_id FK
    bigint lecture_id FK,UK
    bigint current_version_id FK
    int generation
    timestamptz locked_until
    bigint lock_update_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  blocks {
    uuid id PK
    bigint user_id
    bigint note_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  block_revisions {
    bigint id PK
    bigint user_id
    uuid block_id FK
    text kind
    jsonb content
    jsonb attrs
    text author
    text reason
    boolean evidence_unverified
    bigint job_id FK
    bigint note_change_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  note_versions {
    bigint id PK
    bigint user_id
    bigint note_id FK
    int version_no
    bigint_array block_revision_ids
    smallint_array depths
    text kind
    text status
    bigint based_on_id FK
    bigint job_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  note_updates {
    bigint id PK
    bigint user_id
    bigint note_id FK
    text trigger
    text status
    int note_generation
    int run_seconds
    bigint result_version_id FK
    text_array completed_stages
    text failed_stage
    text error_code
    timestamptz started_at
    timestamptz finished_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  note_changes {
    bigint id PK
    bigint user_id
    bigint note_id FK
    text origin
    bigint note_update_id FK
    bigint job_id FK
    bigint message_id FK
    bigint reverts_id FK
    text op
    uuid target_block_id FK
    bigint base_revision_id FK
    jsonb proposal
    text decision
    text status
    text wait_reason
    text merge_outcome
    text reason
    bigint applied_version_id FK
    timestamptz resolved_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  citations {
    bigint id PK
    bigint user_id
    bigint block_revision_id FK
    bigint message_id FK
    bigint item_version_id FK
    text kind
    bigint segment_id FK
    bigint segment_version
    bigint source_revision_id FK
    text web_url
    text web_title
    timestamptz web_fetched_at
    timestamptz created_at
  }
  search_entries {
    bigint id PK
    bigint user_id
    bigint course_id FK
    bigint lecture_id FK
    uuid block_id FK,UK
    bigint block_revision_id FK
    bigint segment_id FK,UK
    bigint segment_version
    text body
    vector embedding
    text embedding_model
    bigint deletion_batch_id
    timestamptz created_at
  }
  correction_suggestions {
  }
  courses {
  }
  jobs {
  }
  lectures {
  }
  messages {
  }
  review_item_versions {
  }
  transcript_segments {
  }
  blocks ||--o{ block_revisions : "block_id"
  jobs |o--o{ block_revisions : "job_id"
  note_changes |o--o{ block_revisions : "note_change_id"
  notes ||--o{ blocks : "note_id"
  block_revisions |o--o{ citations : "block_revision_id"
  block_revisions |o--o{ citations : "source_revision_id"
  messages |o--o{ citations : "message_id"
  review_item_versions |o--o{ citations : "item_version_id"
  transcript_segments |o--o{ citations : "segment_id"
  note_versions ||--o{ correction_suggestions : "note_version_id"
  block_revisions |o--o{ note_changes : "base_revision_id"
  blocks |o--o{ note_changes : "target_block_id"
  messages |o--o{ note_changes : "message_id"
  note_changes |o--o{ note_changes : "reverts_id"
  notes ||--o{ note_changes : "note_id"
  note_updates |o--o{ note_changes : "note_update_id"
  jobs |o--o{ note_changes : "job_id"
  note_versions |o--o{ note_changes : "applied_version_id"
  courses |o--o{ notes : "course_id"
  lectures |o--o{ notes : "lecture_id"
  note_updates |o--o{ notes : "lock_update_id"
  note_versions |o--o{ notes : "current_version_id"
  notes ||--o{ note_updates : "note_id"
  note_versions |o--o{ note_updates : "result_version_id"
  jobs |o--o{ note_versions : "job_id"
  notes ||--o{ note_versions : "note_id"
  note_versions |o--o{ note_versions : "based_on_id"
  block_revisions |o--o{ search_entries : "block_revision_id"
  blocks |o--o{ search_entries : "block_id"
  courses ||--o{ search_entries : "course_id"
  lectures |o--o{ search_entries : "lecture_id"
  transcript_segments |o--o{ search_entries : "segment_id"
```

## tutor

```mermaid
erDiagram
  conversations {
    bigint id PK
    bigint user_id
    bigint course_id FK
    text title
    text summary
    bigint summary_upto_id FK
    int generation
    bigint deletion_batch_id
    timestamptz created_at
  }
  messages {
    bigint id PK
    bigint user_id
    bigint conversation_id FK
    text role
    text content
    bigint question_id FK
    text answer_status
    text reflect_need
    text reflect_reason
    text reflect_status
    text learner_status
    timestamptz evidence_as_of
    timestamptz completed_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  citations {
  }
  courses {
  }
  note_changes {
  }
  observations {
  }
  messages |o--o{ citations : "message_id"
  courses ||--o{ conversations : "course_id"
  messages |o--o{ conversations : "summary_upto_id"
  conversations ||--o{ messages : "conversation_id"
  messages |o--o{ messages : "question_id"
  messages |o--o{ note_changes : "message_id"
  messages |o--o{ observations : "message_id"
```

## learner

```mermaid
erDiagram
  concepts {
    bigint id PK
    bigint user_id
    bigint course_id FK
    text name
    text key
    bigint merged_into_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  concept_states {
    bigint user_id PK
    bigint concept_id PK,FK
    text state
    timestamptz last_independent_success_at
    timestamptz last_strong_failure_at
    jsonb basis
    timestamptz computed_at
  }
  observations {
    bigint id PK
    bigint user_id
    bigint concept_id FK
    bigint grading_id FK
    bigint message_id FK
    timestamptz observed_at
    text kind
    text strength
    text item_type
    boolean hint_used
    boolean answer_revealed
    real uncertainty
    text dedupe_key
    timestamptz superseded_at
    bigint superseded_by_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  courses {
  }
  gradings {
  }
  messages {
  }
  review_units {
  }
  concepts |o--o{ concepts : "merged_into_id"
  courses ||--o{ concepts : "course_id"
  concepts ||--o{ concept_states : "concept_id"
  concepts ||--o{ observations : "concept_id"
  gradings |o--o{ observations : "grading_id"
  messages |o--o{ observations : "message_id"
  observations |o--o{ observations : "superseded_by_id"
  concepts ||--o{ review_units : "concept_id"
```

## review

```mermaid
erDiagram
  review_units {
    bigint id PK
    bigint user_id
    bigint concept_id FK
    text objective
    text task_kind
    text response_mode
    int rubric_major
    text status
    bigint replaced_by_id FK
    text fsrs_state
    double stability
    double difficulty
    int step
    timestamptz due_at
    timestamptz postponed_until
    date skip_until
    timestamptz last_review_at
    int reps
    int lapses
    text fsrs_version
    bigint deletion_batch_id
    timestamptz created_at
  }
  review_items {
    bigint id PK
    bigint user_id
    bigint unit_id FK
    bigint current_version_id FK
    text status
    text pause_reason
    int generation
    bigint deletion_batch_id
    timestamptz created_at
  }
  review_item_versions {
    bigint id PK
    bigint user_id
    bigint item_id FK
    int version_no
    text item_type
    jsonb prompt
    jsonb answer
    jsonb rubric
    int prompt_rev
    int answer_rev
    int rubric_rev
    text change
    timestamptz activated_at
    bigint job_id FK
    bigint deletion_batch_id
    timestamptz created_at
  }
  answer_drafts {
    bigint id PK
    bigint user_id
    bigint item_version_id FK
    text client_id
    text content
    int rev
    boolean stale
    timestamptz updated_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  attempts {
    bigint id PK
    bigint user_id
    bigint item_version_id FK
    bigint unit_id FK
    text answer
    text self_rating
    jsonb hints
    boolean answer_revealed
    boolean revealed_before_recall
    timestamptz presented_at
    uuid idempotency_key UK
    bigint deletion_batch_id
    timestamptz created_at
  }
  gradings {
    bigint id PK
    bigint user_id
    bigint attempt_id FK
    int version_no
    text cause
    int rubric_rev
    text status
    text held_reason
    jsonb element_scores
    text verdict
    boolean major_misconception
    boolean passed
    text rating
    jsonb feedback
    timestamptz applied_at
    timestamptz superseded_at
    bigint deletion_batch_id
    timestamptz created_at
  }
  review_logs {
    bigint id PK
    bigint user_id
    bigint unit_id FK
    bigint grading_id FK,UK
    text rating
    timestamptz scheduled_due_at
    timestamptz reviewed_at
    jsonb state_before
    jsonb state_after
    text fsrs_version
    bigint deletion_batch_id
    timestamptz created_at
  }
  schedule_events {
    bigint id PK
    bigint user_id
    bigint unit_id FK
    text kind
    timestamptz to_time
    bigint deletion_batch_id
    timestamptz created_at
  }
  email_digests {
    bigint id PK
    bigint user_id
    date kst_date
    text status
    text provider_id
    timestamptz created_at
  }
  citations {
  }
  concepts {
  }
  jobs {
  }
  observations {
  }
  review_item_versions ||--o{ answer_drafts : "item_version_id"
  review_item_versions ||--o{ attempts : "item_version_id"
  review_units ||--o{ attempts : "unit_id"
  review_item_versions |o--o{ citations : "item_version_id"
  attempts ||--o{ gradings : "attempt_id"
  gradings |o--o{ observations : "grading_id"
  review_item_versions |o--o{ review_items : "current_version_id"
  review_units ||--o{ review_items : "unit_id"
  jobs |o--o{ review_item_versions : "job_id"
  review_items ||--o{ review_item_versions : "item_id"
  gradings ||--o{ review_logs : "grading_id"
  review_units ||--o{ review_logs : "unit_id"
  concepts ||--o{ review_units : "concept_id"
  review_units |o--o{ review_units : "replaced_by_id"
  review_units ||--o{ schedule_events : "unit_id"
```

## platform

```mermaid
erDiagram
  deletion_batches {
    bigint id PK
    bigint user_id
    text root_kind
    bigint root_id
    text mode
    jsonb scope
    timestamptz purge_at
    timestamptz restored_at
    timestamptz purged_at
    timestamptz logged_at
    timestamptz created_at
  }
  jobs {
    bigint id PK
    bigint user_id
    text kind
    text status
    text target_table
    bigint target_id
    int target_generation
    jsonb payload
    text idempotency_key "UK (user_id, idempotency_key)"
    bytea request_hash
    text stage
    int attempt_no
    timestamptz available_at
    text error_code
    timestamptz started_at
    timestamptz finished_at
    timestamptz created_at
  }
  outbox {
    bigint id PK
    bigint user_id
    text kind
    bigint job_id FK
    text stream
    jsonb payload
    timestamptz sent_at
    timestamptz created_at
  }
  job_stages {
    bigint id PK
    bigint user_id
    bigint job_id FK
    text stage
    timestamptz started_at
    timestamptz ended_at
    text outcome
    text error_code
    timestamptz created_at
  }
  ai_calls {
    bigint id PK
    bigint user_id
    bigint job_id FK
    bigint recording_session_id FK
    text provider
    text model
    int input_tokens
    int output_tokens
    int web_searches
    bigint audio_ms
    numeric estimated_usd
    numeric actual_usd
    timestamptz created_at
  }
  cost_reservations {
    bigint id PK
    bigint user_id
    bigint job_id FK
    bigint recording_session_id FK
    date utc_date
    numeric reserved_usd
    numeric settled_usd
    text status
    timestamptz settled_at
    timestamptz created_at
  }
  block_revisions {
  }
  note_versions {
  }
  recording_sessions {
  }
  review_item_versions {
  }
  jobs |o--o{ ai_calls : "job_id"
  recording_sessions |o--o{ ai_calls : "recording_session_id"
  jobs |o--o{ block_revisions : "job_id"
  jobs |o--o{ cost_reservations : "job_id"
  recording_sessions |o--o{ cost_reservations : "recording_session_id"
  jobs ||--o{ job_stages : "job_id"
  jobs ||--o{ outbox : "job_id"
  jobs |o--o{ note_versions : "job_id"
  jobs |o--o{ review_item_versions : "job_id"
```

