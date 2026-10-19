import logging
import asyncio
from typing import Set, Optional, Dict

logger = logging.getLogger(__name__)


class CrawlControlManager:
    """
    Quản lý tín hiệu dừng (Graceful Cancellation) cho các tiến trình cào dữ liệu GitHub (UC-79).
    Hỗ trợ dừng toàn bộ các tiến trình đang chạy hoặc dừng theo session_id cụ thể.
    """

    def __init__(self):
        self._stopped_sessions: Set[str] = set()
        self._global_stop_event = asyncio.Event()
        self._active_sessions: Dict[str, asyncio.Event] = {}

    def register_session(self, session_id: str) -> None:
        """Đăng ký một session cào mới đang hoạt động."""
        self._active_sessions[session_id] = asyncio.Event()
        if session_id in self._stopped_sessions:
            self._stopped_sessions.remove(session_id)
        logger.info(f"Registered active crawl session: {session_id}")

    def unregister_session(self, session_id: str) -> None:
        """Hủy đăng ký sau khi session hoàn tất hoặc bị hủy."""
        self._active_sessions.pop(session_id, None)
        self._stopped_sessions.discard(session_id)
        logger.info(f"Unregistered crawl session: {session_id}")

    def request_stop(self, session_id: Optional[str] = None) -> bool:
        """
        Gửi yêu cầu dừng phiên cào.
        Nếu không truyền session_id: dừng tất cả các phiên cào đang hoạt động.
        """
        if session_id:
            self._stopped_sessions.add(session_id)
            if session_id in self._active_sessions:
                self._active_sessions[session_id].set()
            logger.warning(f"Stop signal sent to crawl session: {session_id}")
            return True
        else:
            self._global_stop_event.set()
            for s_id, event in self._active_sessions.items():
                self._stopped_sessions.add(s_id)
                event.set()
            logger.warning("Global stop signal sent to ALL active crawl sessions.")
            return True

    def is_stop_requested(self, session_id: Optional[str] = None) -> bool:
        """Kiểm tra xem session hiện tại có nhận được tín hiệu dừng hay không."""
        if self._global_stop_event.is_set():
            return True
        if session_id and session_id in self._stopped_sessions:
            return True
        return False

    def reset_global_stop(self) -> None:
        """Reset lại cờ dừng toàn cục khi bắt đầu phiên mới."""
        self._global_stop_event.clear()

    def get_active_sessions(self) -> list:
        """Lấy danh sách các session đang chạy."""
        return list(self._active_sessions.keys())


crawl_control = CrawlControlManager()
