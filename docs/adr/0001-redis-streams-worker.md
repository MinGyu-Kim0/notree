# 작업 큐로 Procrastinate 대신 Redis Streams와 asyncio 워커를 쓴다

> 상태: 일부 대체됨(2026-11-18). Redis Streams 선택은 유지한다. 직접 만드는 asyncio 워커는 [ADR-0017](0017-taskiq-delivery-sdk-retries.md)(Taskiq)로, 커밋 직후 `XADD`와 30초 회수 루프는 [ADR-0019](0019-outbox-and-ack-after-commit.md)(outbox)로, "모든 작업은 멱등"은 [ADR-0018](0018-db-fencing-redis-lease.md)(실행 시도 번호)과 ADR-0019로 바뀌었다.

요구사항 v0.4.1의 COR-002는 PostgreSQL 기반 Procrastinate를 정했지만, 우리는 Redis Streams와 asyncio로 워커를 직접 만든다. Redis를 들인 진짜 이유는 Q&A 답변 토큰 스트리밍과 진행 알림을 DB를 거치지 않고 SSE로 보내기 위해서다(ADR-0005). Redis를 이미 운영하니 큐도 같은 곳으로 옮겼다. 큐 자체의 DB 부하는 작다. 동시 녹음 10개 기준으로 큐 작업은 초당 0.5건 안팎이고, 전사 저장이 초당 약 10건이다. 그래서 "큐를 DB에서 빼면 DB 부하가 크게 준다"는 기대로 이 결정을 다시 읽지 않도록 적어 둔다.

## Consequences

- 작업 상태의 원본은 Postgres의 `jobs` 테이블이다. 행은 도메인 변경과 같은 트랜잭션에서 넣고, 커밋 직후 `XADD`로 작업 ID만 보낸다.
- 커밋한 뒤 `XADD` 전에 프로세스가 죽거나 Redis가 재시작되면 메시지가 사라질 수 있다. 그래서 워커의 회수 루프가 30초마다 대기 중인데 30초 넘게 처리되지 않은 작업을 다시 넣고, 멈춘 소비자의 메시지는 `XAUTOCLAIM`으로 가져온다.
- 같은 작업이 두 번 실행될 수 있다. 모든 작업은 멱등이어야 한다(QUR-004).
- Redis는 디스크에 쓰지 않는다(스냅샷·AOF 끔, 2026-11-19 변경). 이벤트 Stream에 답변 토큰이 실려, 디스크에 남으면 SER-001 4)("생성 도중의 데이터는 영구 저장하지 않는다")에 어긋나기 때문이다. 백업도 하지 않는다. 잃어버린 상태는 Postgres에서 다시 채운다. 재시작으로 잃은 작업 메시지는 회수 루프가 다시 보낸다.
