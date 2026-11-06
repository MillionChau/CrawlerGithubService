import re
import uuid
from datetime import datetime
from typing import Dict, Any, Optional, List
from fastapi import APIRouter, HTTPException, Query, status

from app.db.mongo import mongo_client
from app.db.models import (
    TechReportModel,
    CreateTechReportRequest,
    UpdateTechReportRequest,
    GenerateAIReportRequest,
    AddReportCommentRequest
)
from app.services.report_generator import report_generator
from app.clients.ai_client import ai_client

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


@router.get("/api/v1/reports/{id}/comments", summary="Lấy danh sách bình luận của báo cáo công nghệ")
async def get_report_comments(id: str) -> Dict[str, Any]:
    """
    Lấy toàn bộ bình luận của bài báo cáo phân tích công nghệ.
    """
    comments = await mongo_client.get_tech_report_comments(id)
    return {
        "status": "success",
        "report_id": id,
        "total": len(comments),
        "items": comments
    }


@router.post("/api/v1/reports/{id}/comments", summary="Gửi bình luận cho báo cáo công nghệ", status_code=status.HTTP_201_CREATED)
async def add_report_comment(id: str, body: AddReportCommentRequest) -> Dict[str, Any]:
    """
    Thành viên gửi bình luận đóng góp ý kiến hoặc phản biện cho bài báo cáo công nghệ.
    """
    if not body.content or not body.content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nội dung bình luận không được để trống."
        )

    comment = await mongo_client.add_tech_report_comment(id, body.dict())
    return {
        "status": "success",
        "message": "Bình luận đã được đăng tải thành công.",
        "data": comment
    }


@router.delete("/api/v1/reports/{id}/comments/{comment_id}", summary="Xóa bình luận báo cáo công nghệ")
async def delete_report_comment(id: str, comment_id: str) -> Dict[str, Any]:
    """
    Xóa bình luận khỏi bài báo cáo.
    """
    deleted = await mongo_client.delete_tech_report_comment(comment_id)
    return {
        "status": "success",
        "message": "Bình luận đã được xóa.",
        "deleted": deleted
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


# =============================================================================
# AI REPORT GENERATION & AI STATUS ENDPOINTS
# =============================================================================

@router.post("/api/v1/admin/reports/ai-generate", summary="Khởi tạo báo cáo công nghệ tự động bằng AI", status_code=status.HTTP_201_CREATED)
async def admin_ai_generate_report(body: GenerateAIReportRequest) -> Dict[str, Any]:
    """
    Sử dụng UnoRouter LLM (kết hợp xoay vòng khóa AI API Key) và số liệu thu thập thực tế từ MongoDB
    để tạo tự động một bài phân tích công nghệ chuyên sâu chuẩn Markdown.
    Hỗ trợ cơ chế Heuristic Fallback khi AI offline hoặc chạm trần rate-limit.
    """
    generated = await report_generator.generate_report(
        topic=body.topic,
        category=body.category,
        target_tech=body.target_tech,
        target_repo=body.target_repo,
        month_period=body.month_period,
        include_live_metrics=body.include_live_metrics
    )

    now = datetime.utcnow()
    report_id = str(uuid.uuid4())
    report_status = (body.status or "DRAFT").upper()

    report_dict = {
        "id": report_id,
        "slug": generated.get("slug") or generate_slug(generated.get("title")),
        "title": generated.get("title"),
        "summary": generated.get("summary"),
        "content_markdown": generated.get("content_markdown"),
        "category": generated.get("category", "TREND").upper(),
        "tags": generated.get("tags", []),
        "metrics_snapshot": generated.get("metrics_snapshot", {}),
        "status": report_status,
        "views_count": 0,
        "likes_count": 0,
        "author_id": "ai-assistant",
        "author_name": "DevRadar AI Analyst",
        "created_at": now,
        "updated_at": now,
        "published_at": now if report_status == "PUBLISHED" else None
    }

    if body.save_to_db:
        await mongo_client.create_tech_report(report_dict)

    return {
        "status": "success",
        "message": "AI tech report generated successfully.",
        "ai_generated": generated.get("ai_generated", False),
        "model_used": generated.get("model_used"),
        "saved_to_db": body.save_to_db,
        "data": report_dict
    }


@router.get("/api/v1/admin/reports/monitored-repos", summary="Lấy danh sách các repo đang theo dõi để chọn đánh giá")
async def admin_get_monitored_repos(limit: int = Query(25, ge=1, le=100)) -> List[Dict[str, Any]]:
    """
    Lấy danh sách top repositories trong cơ sở dữ liệu để phục vụ việc chọn nhanh đánh giá chuyên sâu kho mã nguồn (REPOSITORY).
    """
    mongo_client.connect()
    repos = []
    if mongo_client.db is not None:
        try:
            cursor = mongo_client.db["repositories"].find({}).sort("stars", -1).limit(limit)
            async for doc in cursor:
                repos.append({
                    "full_name": doc.get("full_name") or doc.get("name"),
                    "stars": doc.get("stars", 0),
                    "forks": doc.get("forks", 0),
                    "primary_language": doc.get("primary_language", "General"),
                    "health_score": doc.get("health_score") or 85.0
                })
        except Exception as e:
            logger.warning(f"Error fetching monitored repos for report selector: {e}")
    return repos


@router.get("/api/v1/admin/reports/ai-suggestions", summary="Gợi ý các chủ đề báo cáo công nghệ nổi bật")
async def admin_get_ai_report_suggestions() -> Dict[str, Any]:
    """
    Phân tích dữ liệu trong kho MongoDB để đề xuất các chủ đề báo cáo kỹ thuật 'hot' nhất
    cho quản trị viên lựa chọn tạo bài viết:
    - Báo cáo biến động xu hướng tháng (MONTHLY_TREND)
    - Đánh giá chuyên sâu kho mã nguồn (REPOSITORY)
    - Toàn cảnh ngôn ngữ & công nghệ (LANGUAGE / TREND)
    """
    overview = await mongo_client.get_system_overview()
    top_langs = [item.get("language") for item in overview.get("top_languages", []) if item.get("language")]
    
    # Lấy top 3 repos để gợi ý đánh giá repository
    top_repos = []
    if mongo_client.db is not None:
        try:
            cursor = mongo_client.db["repositories"].find({}).sort("stars", -1).limit(3)
            async for r in cursor:
                top_repos.append(r.get("full_name") or r.get("name"))
        except Exception:
            pass

    now = datetime.utcnow()
    current_month_str = f"Tháng {now.month}/{now.year}"
    target_repo_sample = top_repos[0] if top_repos else "freeCodeCamp/freeCodeCamp"

    suggestions = [
        {
            "topic": f"Báo cáo Chuyển dịch Xu hướng Công nghệ & Mã nguồn mở {current_month_str}",
            "category": "MONTHLY_TREND",
            "target_tech": None,
            "target_repo": None,
            "badge": "Xu hướng Tháng",
            "description": f"Phân tích top công nghệ bứt phá, dịch chuyển thị phần và dự báo chu kỳ {current_month_str}."
        },
        {
            "topic": f"Báo cáo Đánh giá Chuyên sâu Kiến trúc & Sức khỏe Kho mã nguồn {target_repo_sample}",
            "category": "REPOSITORY",
            "target_tech": None,
            "target_repo": target_repo_sample,
            "badge": "Đánh giá Repo",
            "description": f"Phân tích 5 trục năng lực, nhịp commit 12 tuần và phán quyết Production Readiness cho {target_repo_sample}."
        },
        {
            "topic": f"Toàn cảnh hệ sinh thái {top_langs[0] if top_langs else 'Python'} và xu hướng phát triển 2026",
            "category": "LANGUAGE",
            "target_tech": top_langs[0] if top_langs else "Python",
            "target_repo": None,
            "badge": "Ngôn ngữ",
            "description": f"Đánh giá độ trưởng thành, tỷ lệ Fork/Star và khuyến nghị áp dụng hệ sinh thái {top_langs[0] if top_langs else 'Python'}."
        },
        {
            "topic": f"So sánh hiệu năng và độ ứng dụng giữa {top_langs[1] if len(top_langs) > 1 else 'Rust'} và {top_langs[2] if len(top_langs) > 2 else 'Go'} trong Microservices",
            "category": "TREND",
            "target_tech": top_langs[1] if len(top_langs) > 1 else "Rust",
            "target_repo": None,
            "badge": "Xu hướng",
            "description": "Phân tích đối trọng kiến trúc, bộ nhớ, concurrency và quyết định áp dụng cho doanh nghiệp."
        },
        {
            "topic": "Sự trỗi dậy của các Framework Full-stack hiện đại và tiêu chuẩn Cloud Native",
            "category": "FRAMEWORK",
            "target_tech": "TypeScript",
            "target_repo": None,
            "badge": "Framework",
            "description": "Xu hướng chuyển dịch kiến trúc Frontend/Backend hợp nhất và Serverless optimization."
        },
        {
            "topic": "Báo cáo an ninh chuỗi cung ứng và chuẩn hóa Container/DevOps cho doanh nghiệp 2026",
            "category": "DEVOPS",
            "target_tech": "Docker",
            "target_repo": None,
            "badge": "DevOps",
            "description": "Quản trị rủi ro bảo mật phụ thuộc, tối ưu CI/CD pipelines và quản trị container."
        }
    ]

    return {
        "total_repositories_analyzed": overview.get("total_repositories", 0),
        "top_detected_technologies": top_langs[:5],
        "top_monitored_repositories": top_repos,
        "suggested_topics": suggestions
    }


@router.get("/api/v1/admin/ai/status", summary="Trạng thái kho khóa AI và tiến trình xoay vòng (Key Swap)")
async def admin_get_ai_status() -> Dict[str, Any]:
    """
    Kiểm tra trạng thái kết nối UnoRouter AI Gateway, số lượng API Key đang kích hoạt,
    số key đang trong hàng chờ Cooldown và nhật ký gọi thành công.
    """
    return ai_client.get_pool_status()


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


