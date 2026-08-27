import os
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "crawl_config.json")

DEFAULT_CRAWL_CONFIG: Dict[str, Any] = {
    "crawl_interval_minutes": 1.5,
    "max_repos_per_job": 5,
    "min_stars": 5,
    "max_stars": 5000,
    "random_page_max": 10,
    "model_retrain_interval_days": 1.0,
    "daily_retrain_max_queries": 3,
    "repository_health_weights": {
        "activity": 0.30,
        "community": 0.25,
        "maintenance": 0.25,
        "growth": 0.20
    },
    "language_health_weights": {
        "density": 0.25,
        "popularity": 0.35,
        "ecosystem": 0.20,
        "growth": 0.20
    },
    "forecasting_default_steps": 3,
    "queries": [
        "stars:5..50",
        "stars:50..500",
        "stars:500..5000",
        "language:python stars:10..500",
        "language:javascript stars:10..500",
        "language:typescript stars:10..500",
        "language:go stars:10..500",
        "language:rust stars:10..500",
        "language:csharp stars:10..500",
        "language:java stars:10..500",
        "language:cpp stars:10..500",
        "topic:machine-learning stars:>10",
        "topic:fastapi stars:>5",
        "topic:ai stars:>10"
    ],
    "sort_options": ["updated", "stars", "forks"]
}


class CrawlConfigManager:
    """
    Quản lý cấu hình & mockdata cho cả Crawler và các Mô Hình ML (Retrain & Health Weights).
    Cho phép đọc/ghi động từ file JSON hoặc API để cấu hình sau này.
    """

    @classmethod
    def load_config(cls) -> Dict[str, Any]:
        """
        Nạp cấu hình từ file crawl_config.json. 
        Nếu chưa có file thì trả về DEFAULT_CRAWL_CONFIG.
        """
        if os.path.exists(CONFIG_FILE_PATH):
            try:
                with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    return {**DEFAULT_CRAWL_CONFIG, **config}
            except Exception as e:
                logger.warning(f"Failed to read crawl_config.json: {e}. Using default mockdata config.")
        return DEFAULT_CRAWL_CONFIG.copy()

    @classmethod
    def save_config(cls, new_config: Dict[str, Any]) -> bool:
        """
        Lưu cấu hình mới vào file crawl_config.json.
        """
        try:
            current = cls.load_config()
            merged = {**current, **new_config}
            with open(CONFIG_FILE_PATH, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            logger.info("Successfully updated crawl_config.json")
            return True
        except Exception as e:
            logger.error(f"Failed to save crawl_config.json: {e}")
            return False

    @classmethod
    def get_queries(cls) -> List[str]:
        return cls.load_config().get("queries", DEFAULT_CRAWL_CONFIG["queries"])

    @classmethod
    def get_sort_options(cls) -> List[str]:
        return cls.load_config().get("sort_options", DEFAULT_CRAWL_CONFIG["sort_options"])

    @classmethod
    def get_max_repos(cls) -> int:
        return int(cls.load_config().get("max_repos_per_job", 5))

    @classmethod
    def get_interval_minutes(cls) -> float:
        return float(cls.load_config().get("crawl_interval_minutes", 1.5))

    @classmethod
    def get_random_page_max(cls) -> int:
        return int(cls.load_config().get("random_page_max", 10))

    @classmethod
    def get_model_retrain_interval_days(cls) -> float:
        return float(cls.load_config().get("model_retrain_interval_days", 1.0))

    @classmethod
    def get_daily_retrain_max_queries(cls) -> int:
        return int(cls.load_config().get("daily_retrain_max_queries", 3))

    @classmethod
    def get_repository_health_weights(cls) -> Dict[str, float]:
        return cls.load_config().get("repository_health_weights", DEFAULT_CRAWL_CONFIG["repository_health_weights"])

    @classmethod
    def get_language_health_weights(cls) -> Dict[str, float]:
        return cls.load_config().get("language_health_weights", DEFAULT_CRAWL_CONFIG["language_health_weights"])

    @classmethod
    def get_forecasting_steps(cls) -> int:
        return int(cls.load_config().get("forecasting_default_steps", 3))
