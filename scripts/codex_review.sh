#!/usr/bin/env bash
# Codex PR 리뷰를 기다리고, 지적에 답글을 단 뒤 스레드를 resolve한다. AGENTS.md 'git 규칙' 참고.
#
#   scripts/codex_review.sh wait <PR 번호>
#     PR 머리 커밋의 Codex 리뷰가 끝날 때까지 30초마다 확인하고(최대 30분), 열린 Codex 지적을 출력한다.
#     끝나면 0, 시간이 지나면 2로 끝난다.
#   scripts/codex_review.sh resolve <PR 번호> <댓글 ID> <스레드 ID> <답글>
#     지적 댓글에 답글을 달고 그 스레드를 resolve한다. ID는 wait 출력에 있다.
set -euo pipefail

BOT=chatgpt-codex-connector
cmd=${1:-}
pr=${2:-}
[ -n "$cmd" ] && [ -n "$pr" ] || { sed -n '2,9p' "$0"; exit 1; }
repo=$(gh repo view --json nameWithOwner --jq .nameWithOwner)

threads() {
  gh api graphql -F owner="${repo%/*}" -F name="${repo#*/}" -F pr="$pr" -f query='
    query($owner: String!, $name: String!, $pr: Int!) {
      repository(owner: $owner, name: $name) { pullRequest(number: $pr) {
        reviewThreads(first: 100) { nodes { id isResolved path line
          comments(first: 1) { nodes { databaseId author { login } body } } } } } } }' \
    --jq ".data.repository.pullRequest.reviewThreads.nodes[]
          | select(.isResolved | not) | select(.comments.nodes[0].author.login == \"$BOT\")
          | \"스레드 \(.id) · 댓글 \(.comments.nodes[0].databaseId) · \(.path):\(.line)\n\(.comments.nodes[0].body)\n\""
}

case "$cmd" in
  wait)
    head=$(gh pr view "$pr" --json headRefOid --jq .headRefOid)
    for _ in $(seq 60); do
      # 요약 댓글의 <!-- codex-review-state:v1 {...} --> 에 커밋별 리뷰 상태가 있다
      done_for_head=$(gh pr view "$pr" --json comments --jq "
        [.comments[] | select(.author.login == \"$BOT\") | .body
         | capture(\"codex-review-state:v1 (?<s>\\\\{.*?\\\\}) -->\").s | fromjson
         | select(.code_review.commit_sha == \"$head\" and .code_review.status == \"completed\")] | length")
      if [ "$done_for_head" -gt 0 ]; then
        echo "Codex 리뷰 완료 (커밋 ${head:0:7}). 열린 지적:"
        threads
        exit 0
      fi
      sleep 30
    done
    echo "30분 안에 Codex 리뷰가 끝나지 않았다 (커밋 ${head:0:7})" >&2
    exit 2
    ;;
  resolve)
    comment=${3:?댓글 ID}; thread=${4:?스레드 ID}; body=${5:?답글}
    gh api "repos/$repo/pulls/$pr/comments/$comment/replies" -f body="$body" --jq .html_url
    gh api graphql -F id="$thread" -f query='
      mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { isResolved } } }' \
      --jq '"resolved: \(.data.resolveReviewThread.thread.isResolved)"'
    ;;
  *) sed -n '2,9p' "$0"; exit 1 ;;
esac
