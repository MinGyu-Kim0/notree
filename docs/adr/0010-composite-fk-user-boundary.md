# 사용자 경계는 RLS와 (user_id, parent_id) 복합 FK로 DB에서 강제한다

SER-002 3)은 사용자 범위 제한을 애플리케이션과 DB 양쪽에서 하라고 하고, 다른 사용자 자료 노출은 출시 차단 항목이다. 모든 사용자 테이블에 `user_id`와 RLS를 두는 것만으로는 부족하다. FK 검사는 RLS를 거치지 않으므로, 단일 키 FK면 앱 버그 하나로 내 행이 다른 사용자의 강의 ID를 가리킬 수 있고 DB는 막지 못한다. 그래서 부모 테이블마다 `UNIQUE (user_id, id)`를 두고, 자식은 `(user_id, parent_id) → parent (user_id, id)` 복합 키로 참조한다. 앱 DB 계정은 `NOBYPASSRLS`이고, 테이블에는 `FORCE ROW LEVEL SECURITY`를 건다. 트랜잭션마다 `SET LOCAL app.user_id`를 설정하고, 설정하지 않으면 빈 결과가 아니라 오류가 나게 한다.

## Consequences

- 부모 테이블마다 `(user_id, id)` 유니크 인덱스가 하나씩 늘어난다. 자식의 FK 인덱스도 `(user_id, parent_id)`로 만든다. RLS가 `user_id = ?` 조건을 붙이므로 부모별 조회에도 이 인덱스가 쓰인다.
- 근거처럼 여러 원본을 가리키는 열은 `ON DELETE SET NULL (열)` 문법으로 원본 열만 비운다. PostgreSQL 15 이상이 필요하다.
- 사용자를 모르는 시점의 조회(세션 확인, 로그인, 회수 루프, 전체 하루 비용)는 값 하나만 돌려주는 `SECURITY DEFINER` 함수로만 연다. 이 함수들이 RLS의 유일한 예외이므로 출시 차단 RLS 테스트에 넣는다.
- `cron`의 여러 사용자 작업과 복원 작업만 `BYPASSRLS` 관리 계정을 쓴다.
