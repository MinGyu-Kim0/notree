# DB 접근은 SQLAlchemy ORM으로 하되, 모델은 매핑만 하고 스키마의 원본은 SQL 파일로 둔다

백엔드 코드를 처음 쓰면서 DB 접근 방식을 정해야 했다. 후보는 psycopg 3으로 SQL을 직접 쓰는 방식과 SQLAlchemy였다. SQL을 직접 쓰면 의존성이 적고 RLS·복합 FK·`SECURITY DEFINER` 함수처럼 DB에 둔 규칙이 코드에 그대로 보인다. 대신 팀원 모두가 조회와 저장마다 SQL 문을 직접 써야 한다. SQLAlchemy는 같은 일을 Python 객체와 메서드로 쓰므로 SQL 문을 직접 쓰는 것보다 러닝커브가 낮다. 그래서 SQLAlchemy ORM을 쓴다. 타입 붙은 모델(`Mapped[...]`) 덕에 `mypy --strict`가 열 이름과 타입 오류를 검사 단계에서 잡는 것은 덤이다. 드라이버는 psycopg 3, 엔진과 세션은 비동기다.

ORM을 쓰면 보통 모델이 스키마의 원본이 되고 마이그레이션도 모델에서 만든다. Notree는 그렇게 하지 않는다. 사용자 경계(RLS 정책, 권한, ADR-0010), `CHECK`, 부분 인덱스, 논리명(`COMMENT`)은 모델로 표현하기 어렵거나 표현해도 SQL보다 읽기 어렵고, ERDCloud 스냅샷도 DB 카탈로그에서 만든다. 원본이 둘이면 어긋난다. 그래서 테이블 정의의 원본은 SQL 파일(`docs/schema-mvp.sql`, `docs/schema-mvp-security.sql`)로 두고, 모델은 이미 있는 테이블에 이름과 타입을 붙이는 매핑으로만 쓴다.

## Consequences

- 모델에는 열 이름과 타입만 적는다. `ForeignKey`, `CheckConstraint`, 인덱스는 적지 않고 `Base.metadata.create_all()`도 부르지 않는다. DB가 기본값을 채우는 열은 `server_default=FetchedValue()`로 표시해서 INSERT 뒤에 값을 받아 온다.
- 모델을 손으로 쓰므로 SQL과 어긋날 수 있다. 매핑한 테이블의 열 집합이 DB와 같은지 테스트(`test_models_match_schema`)가 확인한다. 타입까지는 확인하지 않는다.
- 모델은 그 테이블을 가진 모듈의 `db.py`에 둔다. 다른 모듈의 모델은 import할 수 없으므로(모듈 의존 방향) 모듈을 넘는 `relationship()`은 쓰지 못한다. 다른 모듈의 데이터는 그 모듈의 함수로 읽는다.
- 비동기 세션에서는 지연 로딩이 동작하지 않는다. 모듈 안에서 `relationship()`을 쓸 때는 `selectinload` 같은 옵션으로 미리 읽는다. 세션은 `expire_on_commit=False`로 만들어 커밋 뒤에도 읽은 값을 쓸 수 있다.
- 세션은 `platform`의 `user_tx(user_id)`로만 연다. 이 함수가 트랜잭션을 열고 `app.user_id`를 설정한다. ORM이 RLS를 대신하지 않는다. 자식 행은 부모에서 `user_id`를 복사하는 `INSERT ... SELECT`로 만든다(`insert().from_select()`).
- `SECURITY DEFINER` 함수 호출, `set_config`처럼 모델로 쓸 이유가 없는 쿼리는 `text()`로 SQL을 그대로 쓴다.
- 마이그레이션 도구(Alembic)는 쓰지 않는다. 프로토타입에서는 SQL 파일을 고치고 DB를 처음부터 다시 만든다. 데이터를 지킬 필요가 생기는 시점에 마이그레이션 방식을 정하고, 모델을 원본으로 바꾸려면 이 ADR을 다시 연다.
