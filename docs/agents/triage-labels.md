# 분류 라벨

스킬은 분류 상태를 다섯 가지 역할로 부른다. 이 파일은 그 역할을 이 레포 이슈 트래커의 라벨 이름에 잇는다. 라벨은 `scripts/setup_labels.sh`가 만든다.

| mattpocock/skills의 역할 | 이 레포의 라벨 | 뜻 |
| --- | --- | --- |
| `needs-triage` | `needs-triage` | 분류 대기 |
| `needs-info` | `needs-info` | 작성자의 추가 정보 대기 |
| `ready-for-agent` | `ready-for-agent` | 명세가 끝나 에이전트에 맡길 수 있음 |
| `ready-for-human` | `ready-for-human` | 사람이 직접 구현해야 함 |
| `wontfix` | `wontfix` | 처리하지 않음 |

스킬이 역할을 말하면(예: "AFK 준비 라벨을 붙여라") 위 표의 라벨 이름을 쓴다.

이슈 종류 라벨(`spec`, `feat`, `bug`, `refactor`, `docs`, `chore`)은 이 표와 따로 붙인다. 이슈 하나에 종류 라벨 하나와 상태 라벨 하나가 붙는다.
