import time

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import setup_logger

logger = setup_logger("crawler.request")


def _resolve_trace(request) -> str:
    """Trace id xuyên hệ thống: Ưu tiên traceparent W3C (00-<traceid>-<spanid>-01)
    mà gateway/.NET tự truyền, fallback về X-Request-ID."""
    tp = request.headers.get("traceparent")
    if tp and len(tp) >= 35:
        return tp[3:35]
    return request.headers.get("x-request-id") or "-"


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Ghi log mỗi request: method, path, status, thời gian phản hồi (ms).

    Format đồng bộ với GatewayService và các service .NET để soi chéo
    một request xuyên qua hệ thống bằng trace id.

    Mức log: >= 500 ERROR · >= 400 WARNING · còn lại INFO.
    Bỏ qua /health, /docs*, /redoc, /openapi.json để không làm nhiễu console.
    """

    SKIP_PREFIXES = ("/docs", "/redoc", "/openapi.json")

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == "/health" or any(path.startswith(p) for p in self.SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "[crawler] %s %s -> 500 (%.1f ms) ip=%s trace=%s UNHANDLED_EXCEPTION",
                request.method,
                path,
                elapsed_ms,
                request.client.host if request.client else "unknown",
                _resolve_trace(request),
                exc_info=True,
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        status_code = response.status_code

        # Echo trace id vào response để client/ops đối chiếu
        request_id = request.headers.get("x-request-id")
        if request_id:
            response.headers["X-Request-ID"] = request_id

        caller = request.client.host if request.client else "unknown"
        trace = _resolve_trace(request)

        message = (
            f"[crawler] {request.method} {path} -> {status_code} "
            f"({elapsed_ms:.1f} ms) ip={caller} trace={trace}"
        )

        if status_code >= 500:
            logger.error(message)
        elif status_code >= 400:
            logger.warning(message)
        else:
            logger.info(message)

        return response
