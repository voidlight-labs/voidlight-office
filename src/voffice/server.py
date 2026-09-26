"""Server: serve frontend statis + endpoint snapshot."""

import threading
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from voffice.content import tool_content, turn_content


def create_app(holder, static_dir: Path, db_path: str | None = None,
               open_url: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if open_url:
            threading.Timer(1.5, webbrowser.open, [open_url]).start()
        yield

    app = FastAPI(title="voidlight-office", lifespan=lifespan)

    @app.get("/api/snapshot")
    def get_snapshot():
        snap = holder.snapshot()
        if snap is None:
            return JSONResponse(status_code=503, content={"error": "snapshot belum siap"})
        return snap

    @app.get("/api/content/tool/{call_id}")
    def get_tool_content(call_id: str):
        if not db_path:
            return JSONResponse(status_code=404, content={"error": "db_path tidak diset"})
        data = tool_content(db_path, call_id)
        if data is None:
            return JSONResponse(status_code=404, content={"error": "tool call tidak ditemukan"})
        return data

    @app.get("/api/content/turn/{turn_id}")
    def get_turn_content(turn_id: str):
        if not db_path:
            return JSONResponse(status_code=404, content={"error": "db_path tidak diset"})
        data = turn_content(db_path, turn_id)
        if data is None:
            return JSONResponse(status_code=404, content={"error": "turn tidak ditemukan"})
        return data

    # route /api didaftarkan lebih dulu supaya tidak tertelan mount "/"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


def run_server(holder, config: dict, static_dir: Path, db_path: str | None = None,
               open_browser: bool = True) -> None:
    port = config["server"]["port"]
    url = f"http://127.0.0.1:{port}"
    app = create_app(holder, static_dir, db_path=db_path,
                     open_url=url if open_browser else None)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
