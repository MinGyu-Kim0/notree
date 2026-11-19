#!/usr/bin/env bash
# main과 dev를 처음 push한 뒤 한 번 실행한다. 저장소 관리자 권한이 필요하고, 다시 실행해도 된다.
# main과 dev에는 PR로만, 사람 한 명 이상이 승인한 뒤에 병합되게 한다 (AGENTS.md 'git 규칙').
set -euo pipefail

# 병합 방식은 squash와 merge commit만 남긴다.
gh repo edit --enable-squash-merge --enable-merge-commit --enable-rebase-merge=false --delete-branch-on-merge

# dismiss_stale_reviews=false: 승인 뒤 요구사항 사본 커밋을 올려도 승인이 유지돼야 한다.
# enforce_admins=true: 관리자도 직접 push하지 못한다.
for branch in main dev; do
gh api --method PUT "repos/{owner}/{repo}/branches/$branch/protection" --input - <<'JSON'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": false
  },
  "restrictions": null,
  "allow_force_pushes": false,
  "allow_deletions": false
}
JSON
done
