from starlette.datastructures import Headers
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class UploadLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not scope["path"].startswith("/documents")
        ):
            await self.app(scope, receive, send)
            return
        limit = self.max_bytes + 65536  # Bounded multipart headers and title overhead.
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and (
            len(declared) > 20 or not declared.isdecimal() or int(declared) > limit
        ):
            await JSONResponse(
                {"detail": "La solicitud supera el tamaño permitido"},
                status_code=413,
                headers={"Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        consumed = 0

        async def limited_receive() -> Message:
            nonlocal consumed
            message = await receive()
            consumed += len(message.get("body", b""))
            if consumed > limit:
                scope["upload_too_large"] = True
                # Starlette closes multipart temporary files on MultiPartException.
                raise MultiPartException("upload limit exceeded")
            return message

        await self.app(scope, limited_receive, send)
