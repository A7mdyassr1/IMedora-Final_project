"""Early refusal of oversized photo uploads (B5 CP4).

FastAPI parses (and spools to disk) a multipart body before the endpoint runs, so the endpoint's own
size check alone would still let a client upload a huge file first. This pure ASGI middleware
answers 413 file_too_large BEFORE reading the body when the request's Content-Length already shows
it is too big. Requests without a Content-Length (chunked) still reach the endpoint, which never
keeps more than the limit + 1 byte in memory; production deployments should also cap the request
size at the reverse proxy.
"""
import json
import re

from app.core.config import get_settings

MULTIPART_OVERHEAD = 64 * 1024  # boundaries and part headers around the file


class UploadSizeLimitMiddleware:
    def __init__(self, app, api_prefix: str = "/api/v1"):
        self.app = app
        self.upload_path = re.compile(rf"^{re.escape(api_prefix)}/tickets/[^/]+/attachments/?$")

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and self.upload_path.match(scope["path"]):
            settings = get_settings()
            length = dict(scope.get("headers") or []).get(b"content-length")
            if length is not None and length.isdigit() and int(length) > settings.max_upload_bytes + MULTIPART_OVERHEAD:
                body = json.dumps({"error": {"code": "file_too_large",
                                             "message": f"The file is larger than {settings.max_upload_mb} MB.",
                                             "details": []}}).encode()
                await send({"type": "http.response.start", "status": 413,
                            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                                        (b"connection", b"close")]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
