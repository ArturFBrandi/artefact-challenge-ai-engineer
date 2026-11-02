"""Chat API and page. The session id is a credential, so it lives in an HttpOnly cookie."""

import logging
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from emporio.service import AgentService

logger = logging.getLogger(__name__)

COOKIE = "emporio_session"
COOKIE_DAYS = 7
INDEX = Path(__file__).parent / "static" / "index.html"
MAX_MESSAGE_LENGTH = 2000


class MessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_MESSAGE_LENGTH)


class MessageOut(BaseModel):
    reply: str
    turn: int
    debug: dict[str, Any]


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


class SessionLocks:
    """One turn at a time per session, so a double submit cannot race. Single-process only."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._busy: set[str] = set()

    def acquire(self, session_id: str) -> bool:
        with self._guard:
            if session_id in self._busy:
                return False
            self._busy.add(session_id)
            return True

    def release(self, session_id: str) -> None:
        with self._guard:
            self._busy.discard(session_id)


def create_app(service: AgentService) -> FastAPI:
    app = FastAPI(title="Empório da Música agent", docs_url=None, redoc_url=None)
    locks = SessionLocks()

    def _set_cookie(response: Response, session_id: str) -> None:
        response.set_cookie(
            COOKIE,
            session_id,
            max_age=COOKIE_DAYS * 86400,
            httponly=True,
            samesite="lax",
        )

    def _session(request: Request) -> str | None:
        session_id = request.cookies.get(COOKIE)
        return session_id if session_id and service.session_exists(session_id) else None

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, __: RequestValidationError) -> JSONResponse:
        return _error(422, "invalid_message", f"Send 1 to {MAX_MESSAGE_LENGTH} characters.")

    @app.exception_handler(Exception)
    async def unexpected(_: Request, error: Exception) -> JSONResponse:
        logger.exception("Unhandled error", exc_info=error)
        return _error(500, "internal_error", "Something went wrong. Please try again.")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(INDEX)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/messages", response_model=None)
    def post_message(body: MessageIn, request: Request) -> JSONResponse | dict[str, Any]:
        text = body.message.strip()
        if not text:
            return _error(422, "invalid_message", f"Send 1 to {MAX_MESSAGE_LENGTH} characters.")
        session_id = _session(request) or service.create_session()
        if not locks.acquire(session_id):
            return _error(409, "turn_in_progress", "Still answering your previous message.")
        try:
            result = service.handle_message(session_id, text)
        finally:
            locks.release(session_id)
        response = JSONResponse(
            MessageOut(reply=result.reply, turn=result.turn, debug=result.debug).model_dump()
        )
        _set_cookie(response, session_id)
        return response

    @app.get("/api/history")
    def history(request: Request) -> dict[str, Any]:
        session_id = _session(request)
        return {"messages": service.transcript(session_id) if session_id else []}

    @app.post("/api/reset")
    def reset() -> JSONResponse:
        response = JSONResponse({"messages": []})
        response.delete_cookie(COOKIE)
        return response

    return app
