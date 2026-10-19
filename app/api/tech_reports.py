import re
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Query, status

from app.db.mongo import mongo_client
from app.db.models import (
    TechReportModel,
    CreateTechReportRequest,
    UpdateTechReportRequest
)

router = APIRouter(tags=["Tech Reports & CMS (UC-35..38, UC-64..68)"])


def generate_slug(text: str) -> str:
    """Tạo slug URL thân thiện từ tiêu đề."""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text).strip('-')
    return f"{text}-{uuid.uuid4().hex[:6]}"


# =============================================================================
# CLIENT ENDPOINTS (UC-35, UC-36, UC-38)
# =============================================================================

@router.get("/api/v1/reports", summary="Xem danh sách báo cáo công nghệ đã xuất bản (UC-35)")
async def get_published_reports(
    page: int = Query(1, ge=1, description="Trang hiện tại"),
    limit: int = Query(10, ge=1, le=50, description="Số lượng báo cáo trên 1 trang"),
    category: Optional[str] = Query(None, description="Lọc theo chuyên mục: TREND, LANGUAGE, FRAMEWORK, DEVOPS"),
    search: Optional[str] = Query(None, description="Tìm kiếm theo từ khóa trong tiêu đề hoặc tóm tắt")
) -> Dict[str, Any]:
    """
    UC-35: Khách và thành viên xem danh sách các bài phân tích xu hướng công nghệ đã được duyệt xuất bản (PUBLISHED).
    """
    total, items = await mongo_client.get_tech_reports(
        page=page,
        limit=limit,
        status="PUBLISHED",
        category=category,
        search=search
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": items
    }


@router.get("/api/v1/reports/{id_or_slug}", summary="Xem chi tiết báo cáo công nghệ (UC-36)")
async def get_published_report_detail(id_or_slug: str) -> Dict[str, Any]:
    """
    UC-36: Xem chi tiết bài báo cáo công nghệ qua ID hoặc Slug URL thân thiện.
    Hệ thống tự động tăng biến đếm lượt đọc (views_count).
    """
    report = await mongo_client.get_tech_report_by_id_or_slug(id_or_slug, increment_views=True)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy báo cáo công nghệ: {id_or_slug}"
        )
    return report


@router.post("/api/v1/reports/{id}/like", summary="Thích / Bỏ thích báo cáo công nghệ (UC-38)")
async def toggle_report_like(id: str, increment: bool = Query(True, description="True để like, False để unlike")) -> Dict[str, Any]:
    """
    UC-38: Tương tác thả tim / yêu thích bài báo cáo phân tích công nghệ.
    """
    new_likes = await mongo_client.toggle_tech_report_like(id, increment=increment)
    return {
        "status": "success",
        "report_id": id,
        "likes_count": new_likes,
        "message": "Liked successfully" if increment else "Unliked successfully"
    }


# =============================================================================
# ADMIN CMS ENDPOINTS (UC-64 → UC-68)
# =============================================================================

@router.get("/api/v1/admin/reports", summary="Danh sách quản trị báo cáo công nghệ (UC-64)")
async def admin_get_reports(
    page: int = Query(1, ge=1, description="Trang hiện tại"),
    limit: int = Query(20, ge=1, le=100, description="Số lượng bản ghi trên một trang"),
    status: Optional[str] = Query(None, description="Lọc theo trạng thái: DRAFT, PUBLISHED, ARCHIVED"),
    category: Optional[str] = Query(None, description="Lọc theo danh mục"),
    search: Optional[str] = Query(None, description="Tìm kiếm từ khóa")
) -> Dict[str, Any]:
    """
    UC-64: Quản trị viên xem danh sách toàn bộ báo cáo kỹ thuật (gồm cả bản nháp DRAFT, đã duyệt PUBLISHED và bị ẩn ARCHIVED).
    """
    total, items = await mongo_client.get_tech_reports(
        page=page,
        limit=limit,
        status=status,
        category=category,
        search=search
    )
    return {
        "total": total,
        "page": page,
        "limit": limit,
        "items": items
    }


@router.get("/api/v1/admin/reports/{id}", summary="Xem chi tiết báo cáo phía Admin (UC-65)")
async def admin_get_report_detail(id: str) -> Dict[str, Any]:
    """
    UC-65: Quản trị viên xem đầy đủ nội dung bài viết và metrics snapshot để phê duyệt.
    """
    report = await mongo_client.get_tech_report_by_id_or_slug(id, increment_views=False)
    if not report:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy báo cáo với ID: {id}"
        )
    return report


@router.post("/api/v1/admin/reports", summary="Tạo mới báo cáo công nghệ (UC-66)", status_code=status.HTTP_201_CREATED)
async def admin_create_report(body: CreateTechReportRequest) -> Dict[str, Any]:
    """
    UC-66: Quản trị viên soạn thảo và lưu bản nháp báo cáo công nghệ mới.
    """
    now = datetime.utcnow()
    report_id = str(uuid.uuid4())
    slug = body.slug or generate_slug(body.title)

    report_dict = {
        "id": report_id,
        "slug": slug,
        "title": body.title,
        "summary": body.summary,
        "content_markdown": body.content_markdown,
        "category": body.category.upper(),
        "tags": [t.strip().lower() for t in body.tags if t.strip()],
        "metrics_snapshot": body.metrics_snapshot or {},
        "status": (body.status or "DRAFT").upper(),
        "views_count": 0,
        "likes_count": 0,
        "author_id": "admin",
        "author_name": "DevRadar Administrator",
        "created_at": now,
        "updated_at": now,
        "published_at": now if (body.status or "").upper() == "PUBLISHED" else None
    }

    await mongo_client.create_tech_report(report_dict)
    return {
        "status": "success",
        "message": "Tech report created successfully.",
        "data": report_dict
    }


@router.put("/api/v1/admin/reports/{id}", summary="Cập nhật nội dung báo cáo công nghệ")
async def admin_update_report(id: str, body: UpdateTechReportRequest) -> Dict[str, Any]:
    """
    Chỉnh sửa nội dung, danh mục, tags hoặc snapshot số liệu của báo cáo.
    """
    existing = await mongo_client.get_tech_report_by_id_or_slug(id, increment_views=False)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy báo cáo với ID: {id}"
        )

    update_fields = {}
    if body.title is not None:
        update_fields["title"] = body.title
    if body.summary is not None:
        update_fields["summary"] = body.summary
    if body.content_markdown is not None:
        update_fields["content_markdown"] = body.content_markdown
    if body.category is not None:
        update_fields["category"] = body.category.upper()
    if body.tags is not None:
        update_fields["tags"] = [t.strip().lower() for t in body.tags if t.strip()]
    if body.metrics_snapshot is not None:
        update_fields["metrics_snapshot"] = body.metrics_snapshot
    if body.slug is not None:
        update_fields["slug"] = body.slug

    if update_fields:
        await mongo_client.update_tech_report(id, update_fields)

    updated = await mongo_client.get_tech_report_by_id_or_slug(id, increment_views=False)
    return {
        "status": "success",
        "message": "Tech report updated successfully.",
        "data": updated
    }


@router.put("/api/v1/admin/reports/{id}/publish", summary="Duyệt xuất bản báo cáo phân tích (UC-66)")
async def admin_publish_report(id: str) -> Dict[str, Any]:
    """
    UC-66: Quản trị viên phê duyệt xuất bản bài phân tích ra cộng đồng (trạng thái PUBLISHED).
    """
    existing = await mongo_client.get_tech_report_by_id_or_slug(id, increment_views=False)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy báo cáo với ID: {id}"
        )

    now = datetime.utcnow()
    await mongo_client.update_tech_report(id, {
        "status": "PUBLISHED",
        "published_at": now
    })

    return {
        "status": "success",
        "message": f"Báo cáo '{existing.get('title')}' đã được xuất bản thành công.",
        "status_code": "PUBLISHED",
        "published_at": now.isoformat()
    }


@router.put("/api/v1/admin/reports/{id}/hide", summary="Ẩn báo cáo phân tích (UC-67)")
async def admin_hide_report(id: str) -> Dict[str, Any]:
    """
    UC-67: Quản trị viên chuyển trạng thái báo cáo sang ARCHIVED để ẩn khỏi cộng đồng mà không làm mất dữ liệu.
    """
    existing = await mongo_client.get_tech_report_by_id_or_slug(id, increment_views=False)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy báo cáo với ID: {id}"
        )

    await mongo_client.update_tech_report(id, {
        "status": "ARCHIVED"
    })

    return {
        "status": "success",
        "message": f"Báo cáo '{existing.get('title')}' đã được chuyển sang trạng thái ARCHIVED (Ẩn).",
        "status_code": "ARCHIVED"
    }


@router.delete("/api/v1/admin/reports/{id}", summary="Xóa vĩnh viễn báo cáo phân tích (UC-68)")
async def admin_delete_report(id: str) -> Dict[str, Any]:
    """
    UC-68: Quản trị viên xóa vĩnh viễn báo cáo công nghệ khỏi cơ sở dữ liệu.
    """
    existing = await mongo_client.get_tech_report_by_id_or_slug(id, increment_views=False)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy báo cáo với ID: {id}"
        )

    await mongo_client.delete_tech_report(id)
    return {
        "status": "success",
        "message": f"Báo cáo '{existing.get('title')}' đã được xóa hoàn toàn.",
        "deleted_id": id
    }
