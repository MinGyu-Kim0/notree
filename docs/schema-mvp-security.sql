-- Notree MVP 보안: 역할·RLS·권한. schema-mvp.sql 다음에 슈퍼유저로 실행한다.

-- ─── 역할 ──────────────────────────────────────────────────────
-- 테이블은 마이그레이션 계정이 소유한다. 앱 계정은 소유자가 아니므로 RLS를 그대로 받는다.
CREATE ROLE notree_app LOGIN NOBYPASSRLS;    -- api, realtime, worker
CREATE ROLE notree_admin LOGIN BYPASSRLS;    -- cron(만료·휴지통·탈퇴 삭제)

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO notree_app, notree_admin;
ALTER ROLE notree_app SET statement_timeout = '30s';
ALTER ROLE notree_app SET idle_in_transaction_session_timeout = '30s';

-- ─── RLS ───────────────────────────────────────────────────────
-- 트랜잭션마다 SET LOCAL app.user_id. 설정하지 않고 조회하면 오류가 난다.
-- (SELECT ...)로 감싸 쿼리당 한 번만 평가한다.
DO $$
DECLARE
  t text;
BEGIN
  FOR t IN
    SELECT table_name FROM information_schema.columns
    WHERE table_schema = 'public' AND column_name = 'user_id' AND table_name <> 'sessions'
  LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY own ON %I
      USING ((SELECT current_setting('app.user_id')::bigint) = user_id)$p$, t);
  END LOOP;
END $$;

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
CREATE POLICY own ON users USING ((SELECT current_setting('app.user_id')::bigint) = id);
-- sessions는 쿠키 해시로 사용자를 찾는 표라 그 시점엔 사용자를 모른다. RLS 없이 token_hash로만 조회한다.

-- ─── 권한 ──────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO notree_app, notree_admin;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO notree_app, notree_admin;
-- 영구 삭제는 cron만. 탈퇴는 7일 유예 뒤 지운다 (SFR-045)
REVOKE DELETE ON users, block_revisions, observations, usage_ledger FROM notree_app;
-- 바꾸지 않는 기록
REVOKE UPDATE ON block_revisions, observations FROM notree_app;

-- LangGraph 체크포인트 (ADR-0023). worker가 시작할 때 setup()으로 이 스키마에 테이블을 만든다.
-- 테이블에 user_id가 없어 RLS를 받지 않는다. 담기는 것은 노트·강의 내용이고 질문 원문은 아니다.
-- shortcut: api와 worker가 같은 notree_app 계정이라 DB 권한으로는 api의 접근을 막지 못하고, setup()이 만든 테이블은
--   notree_app이 소유한다('앱 계정은 소유자가 아니다'의 예외), 계정을 나눌 때 notree_worker로 옮기고 소유자를 notree_admin으로 바꾼다
CREATE SCHEMA langgraph;
GRANT USAGE, CREATE ON SCHEMA langgraph TO notree_app;
GRANT USAGE ON SCHEMA langgraph TO notree_admin;
ALTER DEFAULT PRIVILEGES FOR ROLE notree_app IN SCHEMA langgraph GRANT SELECT, DELETE ON TABLES TO notree_admin;   -- cron이 삭제·탈퇴 때 thread를 지운다

-- ─── 사용자를 모르는 시점의 함수 (RLS 예외) ───────────────────
CREATE FUNCTION login_user(p_google_sub text, p_email text) RETURNS bigint
  LANGUAGE sql VOLATILE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  INSERT INTO users (google_sub, email) VALUES (p_google_sub, p_email)
  ON CONFLICT (google_sub) DO UPDATE SET email = EXCLUDED.email
  RETURNING id
$$;

-- 전체 하루 한도 확인. 예약(held)은 날짜가 바뀌어도 더한다 (PER-003 2)
CREATE FUNCTION global_spend(p_utc_date date) RETURNS numeric
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT coalesce(sum(cost_usd) FILTER (WHERE status = 'settled' AND utc_date = p_utc_date), 0)
       + coalesce(sum(reserved_usd) FILTER (WHERE status = 'held'), 0)
  FROM usage_ledger
$$;

ALTER FUNCTION login_user(text, text) OWNER TO notree_admin;
ALTER FUNCTION global_spend(date) OWNER TO notree_admin;
REVOKE EXECUTE ON FUNCTION login_user(text, text), global_spend(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION login_user(text, text), global_spend(date) TO notree_app;

-- ─── 회수 루프: 여러 사용자의 행을 훑는 함수 (RLS 예외, ADR-0010) ───
-- 다시 보낼 작업 전달 (ADR-0019). 보내지 못한 행과, 보냈는데도 오래 queued인 행(Redis에서 메시지를 잃음)이다.
-- 워커는 queued인 작업만 가져가므로 두 번 보내도 한 번만 돈다
CREATE FUNCTION unsent_outbox(p_older_than interval, p_resend_after interval)
  RETURNS TABLE (outbox_id bigint, job_id bigint, user_id bigint)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT o.id, o.job_id, o.user_id
  FROM outbox o JOIN jobs j ON j.id = o.job_id
  WHERE (o.sent_at IS NULL AND o.created_at < now() - p_older_than)
     OR (j.status = 'queued' AND o.sent_at < now() - p_resend_after)
  ORDER BY o.created_at
$$;

-- running인 채 오래된 작업. 회수 루프가 작업마다 user_tx에서 fail_job으로 끝낸다(실패 처리·예약 해제·실패 훅을 한 트랜잭션으로).
-- 인계가 없어서 그대로 두면 계정 한도와 예약을 계속 잡는다 (schema-mvp.md '작업 전달과 멈춘 작업')
CREATE FUNCTION stalled_jobs(p_qa interval, p_background interval)
  RETURNS TABLE (job_id bigint, user_id bigint)
  LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public
AS $$
  SELECT j.id, j.user_id
  FROM jobs j
  WHERE j.status = 'running'
    AND j.started_at < now() - CASE WHEN j.kind = 'qa_answer' THEN p_qa ELSE p_background END
$$;

ALTER FUNCTION unsent_outbox(interval, interval) OWNER TO notree_admin;
ALTER FUNCTION stalled_jobs(interval, interval) OWNER TO notree_admin;
REVOKE EXECUTE ON FUNCTION unsent_outbox(interval, interval), stalled_jobs(interval, interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION unsent_outbox(interval, interval), stalled_jobs(interval, interval) TO notree_app;
