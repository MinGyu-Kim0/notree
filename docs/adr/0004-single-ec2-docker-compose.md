# EC2 1대에 docker compose로 배포하고 Postgres를 직접 운영한다

개인용 캡스톤 규모라 비용을 가장 중요하게 보고, AWS EC2 한 대에 `web`, `api`, `realtime`, `worker`, `cron`, `postgres`, `redis`를 docker compose로 올린다. 음성 조각, WAL-G 백업, 삭제 기록은 S3에 둔다. 관리형 구성(ECS Fargate, RDS, ElastiCache, ALB)은 월 100달러 이상이 들고, ALB의 연결 정리 대기가 최대 60분이라 180분 녹음을 끝까지 유지하라는 COR-003 4)를 맞추기 어려웠다. 서버 한 대가 죽으면 서비스 전체가 멈춘다. 이 위험은 WAL-G 시점 복구(7일)와 3주 백업, 복원 리허설로 감당한다. 규모가 커지면 DB만 RDS로 옮기는 것이 첫 단계다.

## Consequences

- 릴리스할 때는 새 버전 `realtime` 컨테이너를 하나 더 띄우고, Nginx가 새 녹음 연결만 새 컨테이너로 보낸다. 옛 컨테이너는 진행 중인 녹음이 0개가 되면 내린다(최대 180분). 컨테이너는 녹음마다가 아니라 버전마다 하나다.
- `api`, `worker`, `cron`은 바로 교체한다. 끝내지 못한 작업은 회수 루프가 다시 넣는다(ADR-0001).
- Postgres를 직접 운영하므로 `pg_bigm` 같은 확장을 쓸 수 있다.
