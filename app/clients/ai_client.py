import os
import time
import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import httpx
from app.core.config import settings
from app.core.logging import logger


class AIKeyStatus:
    def __init__(self, key: str):
        self.key = key
        # Che giấu một phần key để log an toàn: sk-0ni3...82Sqf6n
        if len(key) > 12:
            self.masked = f"{key[:6]}...{key[-4:]}"
        else:
            self.masked = "***"
        self.cooldown_until: Optional[datetime] = None
        self.total_calls: int = 0
        self.success_calls: int = 0
        self.rate_limited_count: int = 0
        self.last_used_at: Optional[datetime] = None

    def is_cooling(self) -> bool:
        if self.cooldown_until is None:
            return False
        if datetime.utcnow() >= self.cooldown_until:
            self.cooldown_until = None
            return False
        return True

    def mark_cooling(self, seconds: int = 60):
        self.cooldown_until = datetime.utcnow() + timedelta(seconds=seconds)
        self.rate_limited_count += 1
        logger.warning(
            f"[AI Key Pool] Key {self.masked} hit rate-limit. Placed in cooldown for {seconds}s until {self.cooldown_until.isoformat()}."
        )

    def mark_success(self):
        self.total_calls += 1
        self.success_calls += 1
        self.last_used_at = datetime.utcnow()


class AIClient:
    """
    Client kết nối AI Gateway (UnoRouter / OpenAI-compatible API) chuyên dụng
    cho CrawlerGithubService với cơ chế Key Rotation (Swap Key khi gặp Rate-Limit/429)
    và Graceful Fallback an toàn.
    """

    def __init__(self):
        self.base_url = settings.AI_BASE_URL.rstrip("/")
        self.model = settings.AI_MODEL
        self.timeout = settings.AI_TIMEOUT_SECONDS
        self.enabled = settings.EXTERNAL_AI_ENABLED
        self.keys: List[AIKeyStatus] = []
        self._current_index = 0
        self._lock = asyncio.Lock()
        self._reload_keys()

    def _reload_keys(self):
        """Nạp danh sách khóa AI từ cấu hình hệ thống."""
        raw_keys = settings.get_ai_keys()
        self.keys = [AIKeyStatus(k) for k in raw_keys if k and k.strip()]
        logger.info(f"[AIClient] Initialized with {len(self.keys)} AI API key(s). Model: '{self.model}'.")

    def add_key(self, new_key: str) -> bool:
        """Thêm khóa AI mới vào kho dự phòng (hỗ trợ Admin mở rộng)."""
        clean_key = new_key.strip()
        if not clean_key:
            return False
        for k in self.keys:
            if k.key == clean_key:
                return False
        self.keys.append(AIKeyStatus(clean_key))
        logger.info(f"[AIClient] Added new AI key into pool. Total keys: {len(self.keys)}.")
        return True

    def is_available(self) -> bool:
        """Kiểm tra có ít nhất 1 khóa AI và cờ EXTERNAL_AI_ENABLED = True hay không."""
        return bool(self.enabled and self.keys)

    def get_pool_status(self) -> Dict[str, Any]:
        """Trả về thông tin trạng thái kho khóa AI và tiến trình xoay vòng."""
        now = datetime.utcnow()
        active = [k for k in self.keys if not k.is_cooling()]
        cooling = [k for k in self.keys if k.is_cooling()]

        return {
            "enabled": self.enabled,
            "model": self.model,
            "base_url": self.base_url,
            "total_keys": len(self.keys),
            "active_keys_count": len(active),
            "cooling_keys_count": len(cooling),
            "keys_detail": [
                {
                    "masked": k.masked,
                    "is_active": not k.is_cooling(),
                    "total_calls": k.total_calls,
                    "success_calls": k.success_calls,
                    "rate_limited_count": k.rate_limited_count,
                    "cooldown_remaining_seconds": max(0, int((k.cooldown_until - now).total_seconds())) if k.cooldown_until else 0,
                    "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None
                }
                for k in self.keys
            ]
        }

    async def _get_next_available_key(self) -> Optional[AIKeyStatus]:
        """
        Lấy khóa tiếp theo khả dụng không bị cooldown.
        Áp dụng thuật toán Round-Robin với kiểm tra trạng thái hồi phục (Cooldown check).
        """
        async with self._lock:
            if not self.keys:
                return None

            total = len(self.keys)
            for _ in range(total):
                key_obj = self.keys[self._current_index % total]
                self._current_index = (self._current_index + 1) % total
                if not key_obj.is_cooling():
                    return key_obj

            # Tất cả các key đều đang trong trạng thái cooldown => Tìm key có thời gian chờ ngắn nhất
            earliest_key = min(self.keys, key=lambda k: k.cooldown_until or datetime.max)
            logger.warning("[AIClient] All AI keys are currently rate-limited/in cooldown.")
            return None

    async def chat_completion(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 2500
    ) -> Optional[str]:
        """
        Gửi yêu cầu chat completion đến UnoRouter có cơ chế tự động xoay chuyển khóa (Key Swapping).
        Nếu gặp 429 (Rate Limit) hoặc 403, tự động chuyển sang key kế tiếp để thử lại.
        """
        if not self.is_available():
            logger.warning("[AIClient] AI is disabled or no API keys configured. Skipping AI request.")
            return None

        endpoint = f"{self.base_url}/chat/completions"
        attempts = 0
        max_attempts = len(self.keys)

        while attempts < max_attempts:
            key_obj = await self._get_next_available_key()
            if not key_obj:
                logger.warning("[AIClient] No active key available to execute request.")
                break

            attempts += 1
            headers = {
                "Authorization": f"Bearer {key_obj.key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            try:
                logger.info(f"[AIClient] Sending request with key {key_obj.masked} (attempt {attempts}/{max_attempts})...")
                async with httpx.AsyncClient(timeout=12.0) as client:
                    res = await client.post(endpoint, json=payload, headers=headers)

                    if res.status_code == 200:
                        data = res.json()
                        choices = data.get("choices", [])
                        if choices and "message" in choices[0]:
                            content = choices[0]["message"].get("content", "").strip()
                            if content:
                                key_obj.mark_success()
                                logger.info(f"[AIClient] Request succeeded with key {key_obj.masked}.")
                                return content

                    elif res.status_code in [429, 402, 403]:
                        # Bị giới hạn tần suất gọi hoặc quota => Đưa vào hàng chờ cooldown và thử key kế tiếp
                        logger.warning(
                            f"[AIClient] Key {key_obj.masked} returned HTTP {res.status_code}: {res.text[:150]}. Swapping to next key..."
                        )
                        key_obj.mark_cooling(seconds=60)
                        continue

                    else:
                        logger.warning(
                            f"[AIClient] API returned status {res.status_code}: {res.text[:200]}."
                        )
                        key_obj.mark_cooling(seconds=30)
                        continue

            except httpx.TimeoutException:
                logger.warning(f"[AIClient] Request timed out after 12.0s on key {key_obj.masked}. Falling back to deductive engine immediately.")
                key_obj.mark_cooling(seconds=30)
                break
            except Exception as e:
                logger.warning(f"[AIClient] Request failed on key {key_obj.masked}: {e}")
                key_obj.mark_cooling(seconds=20)
                continue

        logger.error("[AIClient] All AI keys failed or timed out. Falling back to heuristic generator.")
        return None

    async def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 2500
    ) -> Optional[str]:
        """Tiện ích sinh văn bản từ System Prompt và User Prompt."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        return await self.chat_completion(messages, temperature=temperature, max_tokens=max_tokens)


ai_client = AIClient()
