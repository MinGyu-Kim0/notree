-- 로컬 개발용 비밀번호와 시드. 빈 DB에 한 번만 실행되므로 ID는 모두 1부터다.
-- 녹음·노트 생성이 없어도 노트 편집·Q&A·복습을 바로 만들 수 있게, 강의 하나가 끝난 상태를 넣는다.

ALTER ROLE notree_app PASSWORD 'dev';
ALTER ROLE notree_admin PASSWORD 'dev';

INSERT INTO users (google_sub, email, recording_consent_at, ai_consent_at)
VALUES ('dev', 'dev@example.com', now(), now());

INSERT INTO courses (user_id, name, background, terms)
VALUES (1, '운영체제', '컴퓨터공학과 3학년 전공 과목. 교재는 공룡책.', '{프로세스,스레드,문맥 교환,PCB}');

INSERT INTO lectures (user_id, course_id, title) VALUES (1, 1, '3주차: 프로세스와 스레드');

INSERT INTO recordings (user_id, lecture_id, status, context, started_at, ended_at, audio_expires_at)
VALUES (1, 1, 'completed',
        '{"background": "컴퓨터공학과 3학년 전공 과목. 교재는 공룡책.", "terms": ["프로세스", "스레드", "문맥 교환", "PCB"]}',
        now() - interval '2 hours', now() - interval '1 hour', now() + interval '6 days');

INSERT INTO segments (user_id, recording_id, start_ms, end_ms, stt_text, corrected_text) VALUES
  (1, 1,     0,  9000, '프로세스는 실행 중인 프로그램입니다. 디스크에 있는 프로그램이 메모리에 올라와 실행되면 프로세스가 됩니다.', NULL),
  (1, 1,  9000, 21000, '운영체제는 프로세스마다 피씨비라는 자료구조를 두고 상태와 레지스터 값을 저장합니다.',
                       '운영체제는 프로세스마다 PCB라는 자료구조를 두고 상태와 레지스터 값을 저장합니다.'),
  (1, 1, 21000, 34000, '스레드는 프로세스 안의 실행 흐름입니다. 같은 프로세스의 스레드는 코드와 데이터, 힙을 공유하고 스택은 따로 가집니다.', NULL),
  (1, 1, 34000, 47000, '문맥 교환은 실행 중인 프로세스의 상태를 PCB에 저장하고 다음 프로세스의 상태를 복원하는 일입니다. 스레드끼리의 교환이 더 쌉니다.', NULL);

INSERT INTO notes (user_id, kind, lecture_id, course_id, status) VALUES
  (1, 'lecture', 1, NULL, 'completed'),   -- 노트 1: 강의 노트
  (1, 'course', NULL, 1, 'completed');    -- 노트 2: 과목 노트

-- 블록 ID는 UUIDv7이어야 한다(ADR-0013). content는 자식을 뺀 Tiptap 노드 하나다(ADR-0020).
INSERT INTO note_blocks (id, user_id, note_id, position, depth, kind, content, author, sources) VALUES
  ('01930000-0000-7000-8000-000000000001', 1, 1, 1, 0, 'heading',
   '{"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "프로세스"}]}', 'ai', '[]'),
  ('01930000-0000-7000-8000-000000000002', 1, 1, 2, 0, 'paragraph',
   '{"type": "paragraph", "content": [{"type": "text", "text": "프로세스는 실행 중인 프로그램이다. 운영체제는 프로세스마다 PCB에 상태와 레지스터 값을 저장한다."}]}',
   'ai', '[{"segment_id": 1}, {"segment_id": 2}]'),
  ('01930000-0000-7000-8000-000000000003', 1, 1, 3, 0, 'heading',
   '{"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "스레드"}]}', 'ai', '[]'),
  ('01930000-0000-7000-8000-000000000004', 1, 1, 4, 0, 'list_item',
   '{"type": "listItem", "content": [{"type": "text", "text": "프로세스 안의 실행 흐름"}]}', 'ai', '[{"segment_id": 3}]'),
  ('01930000-0000-7000-8000-000000000005', 1, 1, 5, 1, 'list_item',
   '{"type": "listItem", "content": [{"type": "text", "text": "코드·데이터·힙은 공유하고 스택은 따로 가진다"}]}', 'ai', '[{"segment_id": 3}]'),
  ('01930000-0000-7000-8000-000000000011', 1, 2, 1, 0, 'heading',
   '{"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "프로세스와 스레드"}]}', 'ai', '[]'),
  ('01930000-0000-7000-8000-000000000012', 1, 2, 2, 0, 'paragraph',
   '{"type": "paragraph", "content": [{"type": "text", "text": "프로세스는 실행 중인 프로그램이고, 스레드는 그 안의 실행 흐름이다. 스레드는 스택만 따로 가지므로 문맥 교환이 프로세스보다 싸다."}]}',
   'ai', '[{"block_id": "01930000-0000-7000-8000-000000000002"}, {"block_id": "01930000-0000-7000-8000-000000000005"}]');

INSERT INTO block_revisions (user_id, block_id, revision, content, author)
SELECT user_id, id, revision, content, author FROM note_blocks;

INSERT INTO concepts (user_id, course_id, name, key, state, state_updated_at) VALUES
  (1, 1, '프로세스', '프로세스', 'learning', now()),
  (1, 1, '스레드', '스레드', 'unassessed', NULL),
  (1, 1, '문맥 교환', '문맥교환', 'unassessed', NULL);

INSERT INTO review_cards (user_id, concept_id, item_type, prompt, answer, rubric, sources, due_at)
VALUES (1, 2, 'short',
        '{"text": "같은 프로세스의 스레드들이 공유하지 않는 메모리 영역은?"}',
        '{"text": "스택"}',
        '{"criteria": ["스택이라고 답한다"]}',
        '[{"block_id": "01930000-0000-7000-8000-000000000012"}]',
        now());
