from __future__ import annotations

import logging
from typing import Optional, Sequence, Set
from urllib.parse import parse_qs

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse, Response
from starlette.status import HTTP_403_FORBIDDEN
from app.twilio_compat import RequestValidator

logger = logging.getLogger(__name__)


class TwilioRequestValidationMiddleware(BaseHTTPMiddleware):
    """Middleware that validates Twilio webhook signatures."""

    def __init__(
        self,
        app,
        validator: Optional[RequestValidator],
        enabled: bool,
        protected_paths: Optional[Sequence[str]] = None,
    ) -> None:
        super().__init__(app)
        self.validator = validator
        self.enabled = enabled and validator is not None
        self.protected_paths: Set[str] = set(protected_paths or [])

    async def dispatch(self, request: Request, call_next) -> Response:
        if not self.enabled or request.url.path not in self.protected_paths:
            return await call_next(request)

        signature = request.headers.get("X-Twilio-Signature")
        if not signature:
            logger.warning("Missing Twilio signature for %s", request.url.path)
            return PlainTextResponse("Missing Twilio signature", status_code=HTTP_403_FORBIDDEN)

        body = await request.body()
        params = _parse_body(body, request.headers.get("content-type", ""))
        url = str(request.url)

        if not self.validator.validate(url, params, signature):
            logger.warning("Invalid Twilio signature for %s", request.url.path)
            return PlainTextResponse("Invalid Twilio signature", status_code=HTTP_403_FORBIDDEN)

        async def receive() -> dict:
            return {"type": "http.request", "body": body, "more_body": False}

        new_request = Request(request.scope, receive)
        return await call_next(new_request)


def _parse_body(body: bytes, content_type: str):
    if "application/x-www-form-urlencoded" in content_type:
        parsed = parse_qs(body.decode())
        return {key: values[0] if len(values) == 1 else values for key, values in parsed.items()}
    return body.decode()


__all__ = ["TwilioRequestValidationMiddleware"]
