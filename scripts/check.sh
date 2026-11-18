#!/usr/bin/env bash
# 작업을 끝내기 전에 돌리는 검사. --fix를 주면 포맷과 자동 수정되는 린트를 먼저 고친다.
set -euo pipefail
cd "$(dirname "$0")/../backend"

if [ "${1:-}" = "--fix" ]; then
  uv run ruff format .
  uv run ruff check --fix .
else
  uv run ruff format --check .
  uv run ruff check .
fi
uv run mypy
uv run lint-imports
# 테스트는 compose로 띄운 DB(127.0.0.1:54320)에 붙는다. 먼저 README의 실행 명령으로 띄운다.
uv run pytest -q
