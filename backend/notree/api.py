"""api 컨테이너 진입점: uvicorn notree.api:app"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from notree.capture.api import router as capture_router
from notree.platform.db import engine
from notree.platform.jobs import broker


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    await broker.startup()
    yield
    await broker.shutdown()
    await engine.dispose()


app = FastAPI(title="Notree", lifespan=lifespan)
app.include_router(capture_router)  # 모듈 라우터는 여기에 한 줄씩 더한다


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
