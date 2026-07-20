import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.logging_setup import get_logger, setup_logging
from app.repositories.database import init_db

setup_logging()
_req_log = get_logger("request")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="Echo API",
    version="1.0.0",
    description="识境 Echo 后台服务",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录每个后台请求与返回：方法、路径、状态码、耗时。"""
    start = time.perf_counter()
    client = request.client.host if request.client else "-"
    _req_log.info("收到请求 %s %s (来自 %s)", request.method, request.url.path, client)
    try:
        response = await call_next(request)
    except Exception:
        dur_ms = (time.perf_counter() - start) * 1000
        _req_log.exception(
            "请求异常 %s %s (%.1fms)", request.method, request.url.path, dur_ms
        )
        raise
    dur_ms = (time.perf_counter() - start) * 1000
    _req_log.info(
        "返回响应 %s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        dur_ms,
    )
    return response

# 静态文件路由：通过路由提供 data 目录文件（经过 CORS 中间件）
@app.get("/data/{file_path:path}")
async def serve_data_file(file_path: str):
    full = os.path.join("data", file_path)
    if not os.path.exists(full):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(full)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok"}
