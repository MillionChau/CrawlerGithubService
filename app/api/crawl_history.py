from fastapi import APIRouter, HTTPException, Query, status
from typing import Dict, Any, Optional, List
from app.db.mongo import mongo_client
from app.db.models import CrawlLogModel

router = APIRouter(prefix="/api/v1/crawl", tags=["Crawl History & Management (UC-76, UC-77)"])


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
