from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.manager import BenchmarkManager
from app.settings import Settings

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=512)


class ReloadRequest(BaseModel):
    quantization: str


def create_app(
    settings: Settings | None = None,
    manager: BenchmarkManager | None = None,
    load_on_startup: bool = True,
) -> FastAPI:
    service_settings = settings or Settings()
    active_manager = manager or BenchmarkManager(service_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if load_on_startup:
            await active_manager.reload(service_settings.default_quantization)
        yield

    app = FastAPI(
        title="Chinese-CLIP Retrieval Benchmark",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.manager = active_manager
    app.state.reload_task = None

    @app.get("/api/status")
    async def status(request: Request):
        return request.app.state.manager.status()

    @app.post("/api/search")
    async def search(payload: SearchRequest, request: Request):
        try:
            return await request.app.state.manager.search(payload.query)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @app.post("/api/model/reload", status_code=202)
    async def reload_model(payload: ReloadRequest, request: Request):
        active: BenchmarkManager = request.app.state.manager
        current_task = request.app.state.reload_task
        if (
            active.state in {"loading_model", "indexing_images"}
            or current_task is not None
            and not current_task.done()
        ):
            raise HTTPException(status_code=409, detail="Model reload is already running")
        try:
            from app.manager import QUANTIZATIONS

            if payload.quantization not in QUANTIZATIONS:
                raise ValueError("Unsupported quantization")
            active.state = "loading_model"
            task = asyncio.create_task(
                active.reload(payload.quantization)
            )
            task.add_done_callback(
                lambda completed: completed.exception()
                if not completed.cancelled()
                else None
            )
            request.app.state.reload_task = task
            return {"status": "accepted", "quantization": payload.quantization}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/images/{image_id}")
    async def image(image_id: str, request: Request):
        path = request.app.state.manager.find_image(image_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        return FileResponse(path)

    app.mount("/assets", StaticFiles(directory=STATIC_DIR), name="assets")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
