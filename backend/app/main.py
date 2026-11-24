import logging
import sqlite3
from asyncio import Lock
from contextlib import asynccontextmanager
from time import perf_counter
from weakref import WeakValueDictionary

from fastapi import FastAPI, Header, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import Settings
from .gateway import Gateway, ProvidersUnavailable
from .schemas import ChatRequest, ChatResponse, Metadata
from .storage import Storage


logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> CORSMiddleware:
    settings = settings or Settings.from_env()
    storage = Storage(settings.db_path)
    session_locks: WeakValueDictionary[str, Lock] = WeakValueDictionary()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await run_in_threadpool(storage.initialize)
        app.state.gateway = Gateway(settings)
        yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc):
        errors = [{field: error[field] for field in ("loc", "msg", "type")} for error in exc.errors()]
        return JSONResponse({"detail": errors}, status_code=422)

    @app.exception_handler(Exception)
    async def internal_error(_request, exc):
        logger.error("Unexpected request failure (%s)", type(exc).__name__)
        return JSONResponse({"detail": "internal server error"}, status_code=500)

    @app.get("/health")
    async def health():
        try:
            await run_in_threadpool(storage.check)
        except sqlite3.Error:
            raise HTTPException(status_code=503, detail="database unavailable") from None
        return {"status": "ok", "keys_configured": len(app.state.gateway.key_ids), "cache_enabled": True}

    @app.post("/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
        started = perf_counter()
        gateway: Gateway = app.state.gateway
        try:
            failed_keys = gateway.simulated_failures(x_simulate_failure)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None

        # Serialize turns in the same session, while awaiting different sessions concurrently.
        # Active requests keep their lock alive without retaining inactive session IDs in memory.
        lock = session_locks.setdefault(request.session_id, Lock())
        async with lock:
            _, system_prompt, history = await run_in_threadpool(storage.load, request.session_id)
            if request.system_prompt is not None:
                system_prompt = request.system_prompt.strip() or None

            messages = [{"role": "system", "content": system_prompt or settings.default_system_prompt}]
            messages.extend({"role": row["role"], "content": row["content"]} for row in history)
            messages.append({"role": "user", "content": request.message})
            try:
                result = await gateway.complete(messages, failed_keys)
            except ProvidersUnavailable:
                raise HTTPException(status_code=503, detail="all providers unavailable") from None

            metadata = Metadata(
                resolution_source="LLM_CACHE" if result.key_id is None else "LIVE_INFERENCE",
                model=gateway.model,
                latency_ms=int((perf_counter() - started) * 1000),
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                key_id=result.key_id,
                fallback_attempts=result.fallback_attempts,
            )
            await run_in_threadpool(
                storage.save_turn, request.session_id, system_prompt, request.message, result.reply, metadata
            )
        return ChatResponse(session_id=request.session_id, reply=result.reply, metadata=metadata)

    @app.get("/sessions/{session_id:path}/messages")
    async def session_messages(session_id: str):
        found, _, messages = await run_in_threadpool(storage.load, session_id)
        if not found:
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": session_id, "messages": messages}

    return CORSMiddleware(app, allow_origins=list(settings.allowed_origins), allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Simulate-Failure"])
