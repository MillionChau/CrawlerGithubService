import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import httpx

from app.core.config import settings
from app.db.mongo import mongo_client

logger = logging.getLogger(__name__)


class TokenStatus:
    ACTIVE = "ACTIVE"
    RATE_LIMITED = "RATE_LIMITED"
    EXPIRED = "EXPIRED"
    DISABLED = "DISABLED"


class TokenEntry:
    def __init__(
        self,
        token: str,
        description: str = "",
        token_id: Optional[str] = None,
        status: str = TokenStatus.ACTIVE,
        remaining: int = 5000,
        limit: int = 5000,
        reset_at: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.token_id = token_id or str(uuid.uuid4())
        self.token = token.strip()
        self.description = description
        self.status = status
        self.remaining = remaining
        self.limit = limit
        self.reset_at = reset_at
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    @property
    def token_preview(self) -> str:
        if len(self.token) <= 12:
            return "****"
        return f"{self.token[:8]}...{self.token[-4:]}"

    def to_dict(self, hide_token: bool = True) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "token_preview": self.token_preview,
            "token": "********" if hide_token else self.token,
            "description": self.description,
            "status": self.status,
            "remaining": self.remaining,
            "limit": self.limit,
            "reset_at": self.reset_at.isoformat() if self.reset_at else None,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else str(self.created_at),
            "updated_at": self.updated_at.isoformat() if isinstance(self.updated_at, datetime) else str(self.updated_at)
        }


class TokenManager:
    """
    Quản lý Pool API Token GitHub thông minh (Smart Token Pool Rotator).
    - Tự động hoán đổi (Swap) token khi token hiện tại bị 403 Rate Limit hoặc hết quota.
    - Tự động phục hồi trạng thái token khi qua thời điểm reset.
    - Đồng bộ lưu trữ trong MongoDB Atlas để phục vụ cấu hình động từ Admin CMS.
    """
    def __init__(self):
        self.tokens: List[TokenEntry] = []
        self.current_index: int = 0
        self.lock = asyncio.Lock()
        self._initialized: bool = False

    async def initialize(self):
        """Khởi tạo danh sách token từ CSDL MongoDB hoặc cấu hình biến môi trường."""
        async with self.lock:
            if self._initialized:
                return

            # 1. Thử tải danh sách token đã lưu từ MongoDB
            loaded_tokens = []
            if mongo_client.db is not None:
                try:
                    cursor = mongo_client.db["github_tokens"].find({})
                    async for doc in cursor:
                        reset_at = doc.get("reset_at")
                        if isinstance(reset_at, str):
                            try:
                                reset_at = datetime.fromisoformat(reset_at)
                            except Exception:
                                reset_at = None
                        entry = TokenEntry(
                            token=doc.get("token", ""),
                            description=doc.get("description", ""),
                            token_id=doc.get("token_id"),
                            status=doc.get("status", TokenStatus.ACTIVE),
                            remaining=doc.get("remaining", 5000),
                            limit=doc.get("limit", 5000),
                            reset_at=reset_at
                        )
                        loaded_tokens.append(entry)
                except Exception as e:
                    logger.warning(f"Failed to load tokens from MongoDB: {e}")

            # 2. Nạp thêm các token từ biến môi trường (.env) nếu chưa có
            env_tokens = settings.get_initial_tokens()
            existing_token_strs = {t.token for t in loaded_tokens}

            for idx, raw_t in enumerate(env_tokens):
                if raw_t not in existing_token_strs:
                    new_entry = TokenEntry(
                        token=raw_t,
                        description=f"Initial Token from .env #{idx + 1}"
                    )
                    loaded_tokens.append(new_entry)
                    existing_token_strs.add(raw_t)
                    # Lưu vào MongoDB
                    if mongo_client.db is not None:
                        try:
                            await mongo_client.db["github_tokens"].insert_one({
                                "token_id": new_entry.token_id,
                                "token": new_entry.token,
                                "token_preview": new_entry.token_preview,
                                "description": new_entry.description,
                                "status": new_entry.status,
                                "remaining": new_entry.remaining,
                                "limit": new_entry.limit,
                                "reset_at": None,
                                "created_at": new_entry.created_at,
                                "updated_at": new_entry.updated_at
                            })
                        except Exception as e:
                            logger.warning(f"Failed to persist env token to MongoDB: {e}")

            self.tokens = loaded_tokens
            self._initialized = True
            logger.info(f"✨ GitHub TokenManager initialized with {len(self.tokens)} token(s) in pool.")

    async def get_active_token(self) -> Optional[TokenEntry]:
        """
        Lấy một Token đang hoạt động tốt (ACTIVE và còn quota).
        Tự động mở lại các token đã qua thời gian reset_at.
        Tự động xoay vòng sang token tiếp theo nếu token hiện tại bị chặn.
        """
        if not self._initialized:
            await self.initialize()

        async with self.lock:
            if not self.tokens:
                return None

            now = datetime.now(timezone.utc)

            # 1. Kiểm tra và mở khóa các token đã hết thời gian phạt rate-limit
            for t in self.tokens:
                if t.status == TokenStatus.RATE_LIMITED and t.reset_at:
                    reset_time = t.reset_at if t.reset_at.tzinfo else t.reset_at.replace(tzinfo=timezone.utc)
                    if now >= reset_time:
                        t.status = TokenStatus.ACTIVE
                        t.remaining = t.limit
                        t.reset_at = None
                        t.updated_at = datetime.now(timezone.utc)
                        logger.info(f"🔄 Token {t.token_preview} has passed reset time. Restored to ACTIVE.")
                        await self._sync_token_to_db(t)

            # 2. Tìm token active bắt đầu từ current_index
            total = len(self.tokens)
            for i in range(total):
                idx = (self.current_index + i) % total
                candidate = self.tokens[idx]
                if candidate.status == TokenStatus.ACTIVE and candidate.remaining > 5:
                    if idx != self.current_index:
                        logger.info(f"🔀 Token Swapped: Switched from Token #{self.current_index + 1} to #{idx + 1} ({candidate.token_preview})")
                        self.current_index = idx
                    return candidate

            # 3. Nếu không có token nào còn quota > 5, thử lấy token active bất kỳ
            for idx, candidate in enumerate(self.tokens):
                if candidate.status == TokenStatus.ACTIVE:
                    self.current_index = idx
                    return candidate

            logger.error("❌ ALL GitHub tokens in pool are currently RATE_LIMITED or EXPIRED!")
            return None

    async def mark_rate_limited(self, token_str: str, reset_timestamp: Optional[int] = None) -> Optional[TokenEntry]:
        """Đánh dấu token bị rate-limited và chuyển đổi ngay sang token tiếp theo."""
        from datetime import timedelta
        async with self.lock:
            for idx, t in enumerate(self.tokens):
                if t.token == token_str:
                    t.status = TokenStatus.RATE_LIMITED
                    t.remaining = 0
                    if reset_timestamp:
                        t.reset_at = datetime.fromtimestamp(reset_timestamp, timezone.utc)
                    else:
                        # Mặc định phạt 60 giây nếu không có header
                        t.reset_at = datetime.now(timezone.utc) + timedelta(seconds=60)
                    t.updated_at = datetime.now(timezone.utc)
                    logger.warning(f"⚠️ Token #{idx + 1} ({t.token_preview}) marked as RATE_LIMITED until {t.reset_at}.")
                    await self._sync_token_to_db(t)
                    break

            # Tự động nhảy sang token tiếp theo
            if len(self.tokens) > 1:
                self.current_index = (self.current_index + 1) % len(self.tokens)
                next_token = self.tokens[self.current_index]
                logger.info(f"🔄 Automatically swapping to next candidate: Token #{self.current_index + 1} ({next_token.token_preview})")
                return next_token
            return None

    async def mark_expired(self, token_str: str):
        """Đánh dấu token bị lỗi 401 (Bad Credentials / Hết hạn)."""
        async with self.lock:
            for idx, t in enumerate(self.tokens):
                if t.token == token_str:
                    t.status = TokenStatus.EXPIRED
                    t.updated_at = datetime.utcnow()
                    logger.error(f"❌ Token #{idx + 1} ({t.token_preview}) marked as EXPIRED (401 Bad Credentials).")
                    await self._sync_token_to_db(t)
                    break

    async def update_quota(self, token_str: str, remaining: int, limit: int, reset_timestamp: Optional[int] = None):
        """Cập nhật quota còn lại từ header x-ratelimit-remaining của GitHub response."""
        async with self.lock:
            for t in self.tokens:
                if t.token == token_str:
                    t.remaining = remaining
                    t.limit = limit
                    if reset_timestamp:
                        t.reset_at = datetime.fromtimestamp(reset_timestamp, timezone.utc)
                    if remaining <= 0:
                        t.status = TokenStatus.RATE_LIMITED
                    elif t.status == TokenStatus.RATE_LIMITED and remaining > 50:
                        t.status = TokenStatus.ACTIVE
                    t.updated_at = datetime.utcnow()
                    await self._sync_token_to_db(t)
                    break

    async def add_token(self, raw_token: str, description: str = "") -> Dict[str, Any]:
        """Admin thêm token mới vào pool (tự động kiểm tra tính hợp lệ qua GitHub API)."""
        clean_token = raw_token.strip()
        if not clean_token:
            raise ValueError("Token không được để trống")

        # Kiểm tra trùng lặp
        for t in self.tokens:
            if t.token == clean_token:
                raise ValueError(f"Token này đã tồn tại trong pool với mã: {t.token_id}")

        # Kiểm tra tính hợp lệ của token với GitHub
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "DevRadar-Crawler"
        }
        if clean_token.startswith("github_pat_"):
            headers["Authorization"] = f"Bearer {clean_token}"
        else:
            headers["Authorization"] = f"token {clean_token}"

        remaining = 5000
        limit = 5000
        reset_at = None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.get("https://api.github.com/rate_limit", headers=headers)
                if res.status_code == 401:
                    raise ValueError("Token không hợp lệ hoặc đã bị GitHub thu hồi (401 Unauthorized)")
                elif res.status_code == 200:
                    data = res.json()
                    core = data.get("resources", {}).get("core", {})
                    remaining = core.get("remaining", 5000)
                    limit = core.get("limit", 5000)
                    reset_ts = core.get("reset")
                    if reset_ts:
                        reset_at = datetime.fromtimestamp(reset_ts, timezone.utc)
        except httpx.RequestError as e:
            logger.warning(f"Could not verify token online ({e}), proceeding with default quota.")

        entry = TokenEntry(
            token=clean_token,
            description=description,
            remaining=remaining,
            limit=limit,
            reset_at=reset_at
        )

        async with self.lock:
            self.tokens.append(entry)
            await self._sync_token_to_db(entry)

        logger.info(f"✅ Added new GitHub Token {entry.token_preview} to pool. Description: '{description}'")
        return entry.to_dict(hide_token=True)

    async def remove_token(self, token_id: str) -> bool:
        """Admin xóa một token khỏi pool."""
        async with self.lock:
            initial_count = len(self.tokens)
            self.tokens = [t for t in self.tokens if t.token_id != token_id]
            removed = len(self.tokens) < initial_count

            if removed and mongo_client.db is not None:
                try:
                    await mongo_client.db["github_tokens"].delete_one({"token_id": token_id})
                except Exception as e:
                    logger.warning(f"Failed to delete token from MongoDB: {e}")

            return removed

    async def toggle_token(self, token_id: str, is_active: bool) -> Optional[Dict[str, Any]]:
        """Admin bật/tắt kích hoạt token."""
        async with self.lock:
            for t in self.tokens:
                if t.token_id == token_id:
                    t.status = TokenStatus.ACTIVE if is_active else TokenStatus.DISABLED
                    t.updated_at = datetime.utcnow()
                    await self._sync_token_to_db(t)
                    return t.to_dict(hide_token=True)
            return None

    async def list_tokens(self) -> List[Dict[str, Any]]:
        """Lấy danh sách tất cả tokens (ẩn chuỗi bí mật, hiển thị preview và quota)."""
        if not self._initialized:
            await self.initialize()
        return [t.to_dict(hide_token=True) for t in self.tokens]

    async def check_all_tokens(self) -> List[Dict[str, Any]]:
        """Quét và cập nhật quota thực tế của tất cả token trong pool."""
        if not self._initialized:
            await self.initialize()

        for t in self.tokens:
            if t.status == TokenStatus.DISABLED:
                continue

            headers = {
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "DevRadar-Crawler"
            }
            if t.token.startswith("github_pat_"):
                headers["Authorization"] = f"Bearer {t.token}"
            else:
                headers["Authorization"] = f"token {t.token}"

            try:
                async with httpx.AsyncClient(timeout=8.0) as client:
                    res = await client.get("https://api.github.com/rate_limit", headers=headers)
                    if res.status_code == 200:
                        data = res.json()
                        core = data.get("resources", {}).get("core", {})
                        t.remaining = core.get("remaining", t.remaining)
                        t.limit = core.get("limit", t.limit)
                        reset_ts = core.get("reset")
                        if reset_ts:
                            t.reset_at = datetime.fromtimestamp(reset_ts, timezone.utc)
                        if t.remaining > 50 and t.status == TokenStatus.RATE_LIMITED:
                            t.status = TokenStatus.ACTIVE
                        elif t.remaining <= 0:
                            t.status = TokenStatus.RATE_LIMITED
                    elif res.status_code == 401:
                        t.status = TokenStatus.EXPIRED
                    t.updated_at = datetime.utcnow()
                    await self._sync_token_to_db(t)
            except Exception as e:
                logger.warning(f"Error checking rate limit for {t.token_preview}: {e}")

        return [t.to_dict(hide_token=True) for t in self.tokens]

    async def _sync_token_to_db(self, token_entry: TokenEntry):
        """Lưu hoặc cập nhật thông tin token vào MongoDB Atlas."""
        if mongo_client.db is not None:
            try:
                doc = {
                    "token_id": token_entry.token_id,
                    "token": token_entry.token,
                    "token_preview": token_entry.token_preview,
                    "description": token_entry.description,
                    "status": token_entry.status,
                    "remaining": token_entry.remaining,
                    "limit": token_entry.limit,
                    "reset_at": token_entry.reset_at.isoformat() if token_entry.reset_at else None,
                    "created_at": token_entry.created_at,
                    "updated_at": token_entry.updated_at
                }
                await mongo_client.db["github_tokens"].update_one(
                    {"token_id": token_entry.token_id},
                    {"$set": doc},
                    upsert=True
                )
            except Exception as e:
                logger.warning(f"Failed to sync token to MongoDB: {e}")


token_manager = TokenManager()
