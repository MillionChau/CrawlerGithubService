import time
import random
from collections import deque
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import setup_logger

logger = setup_logger("crawler.request")

# Ring buffer lưu trữ tối đa 500 log events gần nhất trong RAM để phục vụ Admin UI
SYSTEM_LOG_BUFFER: deque = deque(maxlen=500)


def add_system_log(
    service: str,
    level: str,
    category: str,
    message: str,
    method: Optional[str] = None,
    path: Optional[str] = None,
    status_code: Optional[int] = None,
    elapsed_ms: Optional[float] = None,
    ip: Optional[str] = None,
    trace_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
):
    """Ghi một bản ghi log thủ công hoặc từ cronjob vào in-memory buffer."""
    log_entry = {
        "id": f"log-{int(time.time() * 1000)}-{random.randint(100, 999)}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": service,
        "level": level.upper(),
        "category": category,
        "message": message,
        "method": method,
        "path": path,
        "status_code": status_code,
        "elapsed_ms": elapsed_ms,
        "ip": ip or "127.0.0.1",
        "trace_id": trace_id or "-",
        "extra": extra or {},
    }
    SYSTEM_LOG_BUFFER.appendleft(log_entry)
    return log_entry


def get_system_log_buffer(limit: int = 200) -> List[Dict[str, Any]]:
    """Lấy danh sách log events từ bộ đệm bộ nhớ theo giới hạn."""
    return list(SYSTEM_LOG_BUFFER)[:limit]


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
    Bỏ qua /health, /docs*, /redoc, /openapi.json và /analytics/system-logs để không làm nhiễu console.
    """

    SKIP_PREFIXES = ("/docs", "/redoc", "/openapi.json", "/analytics/system-logs")

    def __init__(self, app):
        super().__init__(app)

    async def dispatch(self, request, call_next):
        path = request.url.path
        if path == "/health" or any(path.startswith(p) for p in self.SKIP_PREFIXES):
            return await call_next(request)

        start = time.perf_counter()
        caller = request.client.host if request.client else "unknown"
        trace = _resolve_trace(request)

        try:
            response = await call_next(request)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            err_msg = (
                f"[crawler] {request.method} {path} -> 500 ({elapsed_ms:.1f} ms) "
                f"ip={caller} trace={trace} UNHANDLED_EXCEPTION: {str(exc)}"
            )
            logger.error(err_msg, exc_info=True)
            add_system_log(
                service="CrawlerGithubService",
                level="ERROR",
                category="HTTP_REQUEST",
                message=err_msg,
                method=request.method,
                path=path,
                status_code=500,
                elapsed_ms=round(elapsed_ms, 1),
                ip=caller,
                trace_id=trace,
                extra={"error": str(exc)},
            )
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        status_code = response.status_code

        # Echo trace id vào response để client/ops đối chiếu
        request_id = request.headers.get("x-request-id")
        if request_id:
            response.headers["X-Request-ID"] = request_id

        message = (
            f"[crawler] {request.method} {path} -> {status_code} "
            f"({elapsed_ms:.1f} ms) ip={caller} trace={trace}"
        )

        level = "ERROR" if status_code >= 500 else ("WARNING" if status_code >= 400 else "INFO")

        if status_code >= 500:
            logger.error(message)
        elif status_code >= 400:
            logger.warning(message)
        else:
            logger.info(message)

        # Đẩy vào ring buffer cho giao diện Admin Logging
        add_system_log(
            service="CrawlerGithubService",
            level=level,
            category="HTTP_REQUEST",
            message=message,
            method=request.method,
            path=path,
            status_code=status_code,
            elapsed_ms=round(elapsed_ms, 1),
            ip=caller,
            trace_id=trace,
        )

        return response
