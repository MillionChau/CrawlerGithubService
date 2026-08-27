import os
import joblib
from typing import Any, Optional


class ModelManager:
    """
    Quản lý lưu trữ và khôi phục các Model Artifacts bằng Joblib (Model Persistence Layer).
    """

    def __init__(self, base_dir: str = "models"):
        self.base_dir = base_dir
        self.dirs = {
            "repository_health": os.path.join(base_dir, "repository_health"),
            "language_health": os.path.join(base_dir, "language_health"),
            "trend": os.path.join(base_dir, "trend"),
            "forecasting": os.path.join(base_dir, "forecasting"),
        }
        self._ensure_directories()

    def _ensure_directories(self):
        """
        Tạo các thư mục lưu trữ model nếu chưa tồn tại.
        """
        for path in self.dirs.values():
            os.makedirs(path, exist_ok=True)

    def save_model(self, model: Any, category: str, model_name: str) -> str:
        """
        Lưu model artifact xuống đĩa dạng file .joblib.
        """
        target_dir = self.dirs.get(category, self.base_dir)
        os.makedirs(target_dir, exist_ok=True)
        filepath = os.path.join(target_dir, f"{model_name}.joblib")
        joblib.dump(model, filepath)
        return filepath

    def load_model(self, category: str, model_name: str) -> Optional[Any]:
        """
        Tải model artifact từ đĩa lên bộ nhớ.
        """
        target_dir = self.dirs.get(category, self.base_dir)
        filepath = os.path.join(target_dir, f"{model_name}.joblib")
        if os.path.exists(filepath):
            return joblib.load(filepath)
        return None
