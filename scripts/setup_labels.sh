#!/usr/bin/env bash
# GitHub 저장소를 만든 뒤 한 번 실행한다. 이슈 템플릿이 붙이는 라벨을 만든다. 다시 실행해도 된다.
set -euo pipefail

while IFS='|' read -r name color description; do
  gh label create "$name" --color "$color" --description "$description" --force
done <<'LABELS'
spec|5319e7|기능 명세. 하위 feat 이슈로 나눈다
feat|0e8a16|구현 작업 단위
bug|d73a4a|요구사항이나 설계와 다른 동작
refactor|fbca04|동작을 바꾸지 않는 구조 변경
docs|0075ca|문서만 바꾸는 변경
chore|cfd3d7|빌드, 설정, 하네스 변경
needs-triage|ededed|분류 대기
needs-info|d876e3|작성자의 추가 정보 대기
ready-for-agent|1d76db|명세가 끝나 에이전트에 맡길 수 있음
ready-for-human|b60205|사람이 직접 구현해야 함
wontfix|ffffff|처리하지 않음
wayfinder:map|006b75|wayfinder 지도 이슈
wayfinder:research|c5def5|wayfinder 조사 티켓
wayfinder:prototype|c5def5|wayfinder 프로토타입 티켓
wayfinder:grilling|c5def5|wayfinder 질문 정리 티켓
wayfinder:task|c5def5|wayfinder 작업 티켓
LABELS
