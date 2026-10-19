from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
from app.core.token_manager import token_manager

router = APIRouter(prefix="/api/v1/crawl/tokens", tags=["GitHub Token Pool & Key Swap (Admin)"])


class AddTokenRequest(BaseModel):
    token: str = Field(..., description="GitHub Personal Access Token (classic hoặc fine-grained)")
    description: Optional[str] = Field("", description="Ghi chú mô tả token (ví dụ: 'Tài khoản bot 02', 'Backup Token')")


class ToggleTokenRequest(BaseModel):
    is_active: bool = Field(..., description="True để kích hoạt ACTIVE, False để vô hiệu hóa DISABLED")


@router.get("", summary="Xem danh sách tất cả API Tokens trong Pool (Admin)")
async def get_all_tokens() -> Dict[str, Any]:
    """
    Lấy danh sách các GitHub API tokens trong pool xoay vòng (Token Pool Rotation).
    Chuỗi token bí mật được ẩn ký tự ở giữa (token_preview) để đảm bảo an toàn.
    """
    tokens = await token_manager.list_tokens()
    return {
        "total": len(tokens),
        "tokens": tokens
    }


@router.post("", status_code=status.HTTP_201_CREATED, summary="Thêm Token mới vào Pool (Admin)")
async def add_new_token(req: AddTokenRequest) -> Dict[str, Any]:
    """
    Admin thêm token GitHub mới vào pool.
    Hệ thống sẽ tự động gọi GitHub API để kiểm tra tính hợp lệ và lấy hạn mức còn lại trước khi lưu.
    """
    try:
        created = await token_manager.add_token(req.token, req.description)
        return {
            "status": "success",
            "message": "Đã thêm GitHub Token mới vào pool thành công.",
            "token": created
        }
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Lỗi khi thêm token: {str(e)}"
        )


@router.delete("/{token_id}", summary="Xóa một Token khỏi Pool (Admin)")
async def delete_token(token_id: str) -> Dict[str, Any]:
    """
    Admin xóa một token ra khỏi pool xoay vòng.
    """
    deleted = await token_manager.remove_token(token_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy token với mã {token_id}"
        )
    return {
        "status": "success",
        "message": f"Đã xóa token {token_id} khỏi pool thành công."
    }


@router.patch("/{token_id}/toggle", summary="Bật/Tắt kích hoạt một Token (Admin)")
async def toggle_token_status(token_id: str, req: ToggleTokenRequest) -> Dict[str, Any]:
    """
    Bật (ACTIVE) hoặc tạm tắt (DISABLED) một token mà không cần xóa khỏi CSDL.
    """
    updated = await token_manager.toggle_token(token_id, req.is_active)
    if not updated:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Không tìm thấy token với mã {token_id}"
        )
    return {
        "status": "success",
        "message": f"Đã chuyển trạng thái token sang {'ACTIVE' if req.is_active else 'DISABLED'}.",
        "token": updated
    }


@router.post("/check-all", summary="Kiểm tra và đồng bộ lại Quota thực tế của toàn bộ Token (Admin)")
async def check_all_tokens_quota() -> Dict[str, Any]:
    """
    Gửi request kiểm tra hạn mức `/rate_limit` cho tất cả token trong pool để cập nhật số lượt còn lại thực tế.
    """
    updated_tokens = await token_manager.check_all_tokens()
    return {
        "status": "success",
        "message": "Đã đồng bộ lại hạn ngạch cho toàn bộ Token trong pool.",
        "tokens": updated_tokens
    }
