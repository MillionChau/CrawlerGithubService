from fastapi import APIRouter, HTTPException, Query, status
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
from app.db.mongo import mongo_client
from app.db.models import CrawlLogModel
from app.core.crawl_control import crawl_control

router = APIRouter(prefix="/api/v1/crawl", tags=["Crawl History & Management (UC-76, UC-77, UC-79)"])


class StopCrawlRequest(BaseModel):
    session_id: Optional[str] = None


@router.post("/stop", summary="Dừng tiến trình cào dữ liệu GitHub đang chạy (UC-79)")
async def stop_crawl(request: Optional[StopCrawlRequest] = None) -> Dict[str, Any]:
    """
    UC-79: Dừng phiên cào dữ liệu phía Admin.
    Gửi tín hiệu Graceful Cancellation đến tiến trình cào đang thực thi.
    Nếu truyền session_id: dừng phiên cụ thể đó.
    Nếu không truyền: dừng toàn bộ các phiên đang hoạt động.
    """
    session_id = request.session_id if request else None
    active_sessions = crawl_control.get_active_sessions()

    crawl_control.request_stop(session_id=session_id)

    # Nếu có session_id cụ thể, cập nhật log sang STOPPED nếu nó tồn tại
    if session_id:
        log = await mongo_client.get_crawl_log_by_id(session_id)
        if log and log.get("status") == "RUNNING":
            await mongo_client.update_crawl_log(session_id, {
                "status": "STOPPED",
                "error_message": "Stopped by Admin request."
            })

    from app.api.analytics import log_user_activity_internal
    try:
        await log_user_activity_internal(
            username="admin",
            display_name="DevRadar Administrator",
            role="Admin",
            action="STOP_CRAWL",
            action_label=f"Dừng phiên cào dữ liệu GitHub {'(' + session_id + ')' if session_id else '(Toàn bộ phiên đang chạy)'}",
            category="SYSTEM",
            target_type="CRAWLER_SESSION",
            target_name=session_id or "All Sessions",
            details={"stopped_sessions": active_sessions}
        )
    except Exception:
        pass

    return {
        "status": "success",
        "message": f"Stop signal emitted successfully for {'session: ' + session_id if session_id else 'all active crawl sessions'}.",
        "target_session_id": session_id,
        "previously_active_sessions": active_sessions
    }


@router.get("/history", summary="Xem danh sách lịch sử các phiên cào dữ liệu (UC-76)")
async def get_crawl_history(
    page: int = Query(1, ge=1, description="Trang hiện tại"),
    limit: int = Query(20, ge=1, le=100, description="Số lượng bản ghi trên một trang"),
    status: Optional[str] = Query(None, description="Lọc theo trạng thái: RUNNING, SUCCESS, FAILED, STOPPED")
) -> Dict[str, Any]:
    """
    UC-76: Xem lịch sử các phiên cào dữ liệu GitHub.
    Cho phép Admin tra cứu thời gian bắt đầu, kết thúc, tổng repo cào được, số repo mới và trạng thái.
    """
    total, items = await mongo_client.get_crawl_logs(page=page, limit=limit, status=status)
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": items
    }


@router.get("/history/{session_id}", summary="Xem chi tiết một phiên cào dữ liệu (UC-77)")
async def get_crawl_session_detail(session_id: str) -> Dict[str, Any]:
    """
    UC-77: Xem chi tiết một phiên cào dữ liệu cụ thể.
    Trả về danh sách các repo đã xử lý, rate limit còn lại của GitHub API và chi tiết lỗi (nếu có).
    """
    log = await mongo_client.get_crawl_log_by_id(session_id)
    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy phiên cào với session_id: {session_id}"
        )
    return log
