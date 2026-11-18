FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 가상환경을 /app 밖에 둔다. 개발 때 /app에 소스를 마운트해도 가려지지 않는다.
ENV UV_PROJECT_ENVIRONMENT=/venv PATH=/venv/bin:$PATH PYTHONPATH=/app PYTHONUNBUFFERED=1
# 마운트한 소스 폴더에 root 소유 캐시 파일을 남기지 않는다
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_ADDOPTS="-p no:cacheprovider"
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked
COPY . .
