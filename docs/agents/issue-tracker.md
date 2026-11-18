# 이슈 트래커: GitHub

이 레포의 이슈와 명세는 GitHub 이슈로 관리한다. 모든 작업은 `gh` CLI로 한다.

## 이 레포의 규칙

- 이슈 본문은 `.github/ISSUE_TEMPLATE/`의 `spec`·`feat`·`bug` 템플릿 절을 채워 쓰고, 템플릿 머리말의 종류 라벨을 붙인다. 이슈를 새로 만들면 `needs-triage`도 붙인다.
- `feat` 이슈는 상위 `spec` 이슈의 하위 이슈로 연결한다.
- 라벨 목록의 원본은 `scripts/setup_labels.sh`다. 라벨을 더하려면 이 스크립트를 고친다.
- 제목, 브랜치, PR 규칙은 `AGENTS.md`의 'git 규칙'을 따른다.

## 기본 동작

- **이슈 만들기**: `gh issue create --title "..." --body "..." --label "..."`. 여러 줄 본문은 heredoc으로 넘긴다.
- **이슈 읽기**: `gh issue view <번호> --json number,title,body,labels,comments`
- **이슈 목록**: `gh issue list --state open --json number,title,body,labels,comments --jq '[.[] | {number, title, body, labels: [.labels[].name], comments: [.comments[].body]}]'`에 `--label`, `--state` 필터를 붙인다.
- **하위 이슈로 연결**: `gh issue create --parent <상위> ...`로 만들거나, 만든 뒤 `gh issue edit <상위> --add-sub-issue <하위>`(`gh` 2.94 이상)로 잇는다. 이전 버전 `gh`에서는 `gh api --method POST repos/<owner>/<repo>/issues/<상위>/sub_issues -F sub_issue_id=<하위 database id>`를 쓴다(database id는 아래 **막힘** 참고). 하위 이슈 기능을 못 쓰면 하위 본문 첫 줄에 `Part of #<상위>`를 적는다.
- **댓글**: `gh issue comment <번호> --body "..."`
- **라벨 붙이기·떼기**: `gh issue edit <번호> --add-label "..."` / `--remove-label "..."`
- **닫기**: `gh issue close <번호> --comment "..."`

레포는 `git remote -v`로 정해진다. 클론 안에서 실행하면 `gh`가 알아서 찾는다.

## PR을 분류 대상으로 볼지

**PRs as a request surface: no.** _(외부 PR을 기능 요청으로 다루려면 `yes`로 바꾼다. `/triage`가 이 값을 읽는다.)_

`yes`이면 PR도 이슈와 같은 라벨과 상태로 다루고, `gh pr` 명령을 쓴다.

- **PR 읽기**: `gh pr view <번호> --comments`, diff는 `gh pr diff <번호>`
- **분류할 외부 PR 목록**: `gh api --paginate 'repos/{owner}/{repo}/pulls?state=open' --jq '.[] | select(.author_association | IN("OWNER","MEMBER","COLLABORATOR") | not) | {number, title, author: .user.login, author_association, labels: [.labels[].name]}'`
- **댓글·라벨·닫기**: `gh pr comment`, `gh pr edit --add-label`/`--remove-label`, `gh pr close`

GitHub는 이슈와 PR이 번호를 함께 쓰므로 `#42`만으로는 어느 쪽인지 모른다. `gh pr view 42`로 먼저 보고, 없으면 `gh issue view 42`로 본다.

## 스킬이 "이슈 트래커에 올려라"라고 하면

GitHub 이슈를 만든다.

## 스킬이 "관련 티켓을 가져와라"라고 하면

위 **이슈 읽기**대로 읽는다.

## wayfinder 동작

`/wayfinder`가 쓴다. **지도**는 이슈 하나이고, **하위** 이슈가 티켓이다. 아래 `wayfinder:*` 라벨은 `scripts/setup_labels.sh`가 만든다.

- **지도**: `wayfinder:map` 라벨을 붙인 이슈 하나. 본문에 Notes / Decisions-so-far / Fog를 둔다. `gh issue create --label wayfinder:map`
- **하위 티켓**: 지도의 GitHub 하위 이슈로 연결한 이슈(위 **하위 이슈로 연결** 참고). 하위 이슈 기능이 없으면 지도 본문의 작업 목록에 넣고 하위 본문 첫 줄에 `Part of #<지도>`를 적는다. 라벨은 `wayfinder:<종류>`(`research`/`prototype`/`grilling`/`task`)다. 맡으면 작업하는 개발자를 담당자로 지정한다.
- **막힘**: GitHub의 **이슈 의존 관계** 기능을 쓴다. `gh api --method POST repos/<owner>/<repo>/issues/<하위>/dependencies/blocked_by -F issue_id=<막는 이슈 database id>`로 잇는다. database id는 `gh api repos/<owner>/<repo>/issues/<번호> --jq .id`로 얻는다(`#번호`나 `node_id`가 아니다). `issue_dependencies_summary.blocked_by`는 열린 막는 이슈 수다. 의존 관계 기능이 없으면 하위 본문 첫 줄에 `Blocked by: #<번호>, #<번호>`를 적는다. 막는 이슈가 모두 닫히면 풀린 것이다.
- **다음 할 일 찾기**: 지도의 열린 하위 이슈를 나열하고(`gh issue list --state open`, 지도의 하위 이슈·작업 목록 범위), 열린 막는 이슈가 있거나 담당자가 있는 것을 뺀다. 지도 순서상 첫 번째를 고른다.
- **맡기**: `gh issue edit <번호> --add-assignee @me`. 세션의 첫 쓰기다.
- **끝내기**: `gh issue comment <번호> --body "<답>"` 뒤 `gh issue close <번호>`, 그리고 지도의 Decisions-so-far에 요지와 링크를 덧붙인다.
