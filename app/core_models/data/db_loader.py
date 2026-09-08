import os
import json
import logging
import pandas as pd
import numpy as np
from typing import List, Dict, Any
from app.db.mongo import mongo_client

logger = logging.getLogger(__name__)


class DatabaseDataLoader:
    """
    Module tải và tiền xử lý dữ liệu repositories thực tế từ MongoDB Atlas
    phục vụ cho việc Train / Evaluate các Core Models.
    """

    @staticmethod
    async def load_repositories_from_mongo() -> List[Dict[str, Any]]:
        """Tải toàn bộ repositories từ MongoDB Atlas (hỗ trợ cả Motor async & PyMongo sync)."""
        repos = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["repositories"].find({})
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    repos.append(doc)
                logger.info(f"Loaded {len(repos)} repositories from MongoDB Atlas (Async).")
            except Exception as e:
                logger.warning(f"Error loading from Async MongoDB: {e}")

        if not repos and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["repositories"].find({})
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    repos.append(doc)
                logger.info(f"Loaded {len(repos)} repositories from MongoDB Atlas (Sync).")
            except Exception as e:
                logger.warning(f"Error loading from Sync MongoDB: {e}")

        return repos

    @staticmethod
    def load_repositories_from_json(filepath: str = "crawled_data.json") -> List[Dict[str, Any]]:
        """Tải dữ liệu repositories từ file JSON local dự phòng."""
        if os.path.exists(filepath):
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    logger.info(f"Loaded {len(data)} repositories from '{filepath}'.")
                    return data
            except Exception as e:
                logger.error(f"Error reading {filepath}: {e}")
        return []

    @classmethod
    async def get_all_repositories(cls) -> List[Dict[str, Any]]:
        """Lấy dữ liệu ưu tiên từ MongoDB Atlas, nếu rỗng thì fallback sang crawled_data.json."""
        repos = await cls.load_repositories_from_mongo()
        if not repos:
            repos = cls.load_repositories_from_json()
        return repos

    @classmethod
    async def get_language_summary(cls) -> List[Dict[str, Any]]:
        """
        Tổng hợp dữ liệu thực tế theo ngôn ngữ lập trình từ MongoDB Atlas.
        """
        repos = await cls.get_all_repositories()
        if not repos:
            return []

        df = pd.DataFrame(repos)
        if 'primary_language' not in df.columns:
            return []

        df['primary_language'] = df['primary_language'].fillna('Unknown')
        df['stars'] = pd.to_numeric(df['stars'], errors='coerce').fillna(0)
        df['forks'] = pd.to_numeric(df['forks'], errors='coerce').fillna(0)
        df['open_issues'] = pd.to_numeric(df['open_issues'], errors='coerce').fillna(0)

        # Gom nhóm tính toán các chỉ số thống kê thực tế
        grouped = df.groupby('primary_language').agg(
            repository_count=('id', 'count'),
            total_stars=('stars', 'sum'),
            total_forks=('forks', 'sum'),
            avg_stars=('stars', 'mean'),
            avg_forks=('forks', 'mean')
        ).reset_index()

        grouped = grouped.rename(columns={'primary_language': 'language'})
        max_repos = grouped['repository_count'].max()
        max_stars = grouped['total_stars'].max()

        results = []
        for _, row in grouped.iterrows():
            lang = row['language']
            count = row['repository_count']
            stars = row['total_stars']
            forks = row['total_forks']

            # Tính toán chỉ số hoạt động & tăng trưởng tự nhiên dựa trên phân bổ dữ liệu thực
            commit_activity = min(100.0, max(40.0, (stars / max(1.0, max_stars)) * 100.0 + 50.0))
            contributor_activity = min(100.0, max(45.0, (forks / max(1.0, count * 50.0)) * 100.0 + 40.0))
            repo_growth_rate = round(float(np.clip(0.02 + (count / max(1, max_repos)) * 0.15, 0.02, 0.25)), 4)
            star_growth_rate = round(float(np.clip(0.04 + (stars / max(1, max_stars)) * 0.20, 0.03, 0.30)), 4)

            results.append({
                "language": lang,
                "repository_count": int(count),
                "total_stars": int(stars),
                "total_forks": int(forks),
                "commit_activity_index": round(float(commit_activity), 2),
                "contributor_activity_index": round(float(contributor_activity), 2),
                "repo_growth_rate": repo_growth_rate,
                "star_growth_rate": star_growth_rate
            })

        return results

    @classmethod
    async def save_repository_health_evaluations(cls, evaluations: List[Dict[str, Any]]) -> int:
        """Lưu danh sách kết quả đánh giá Repository Health vào MongoDB Atlas kèm timestamp lịch sử."""
        if not evaluations:
            return 0
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.isoformat()
        date_str = now_utc.strftime("%Y-%m-%d")

        docs = []
        for eval_item in evaluations:
            item_copy = dict(eval_item)
            item_copy["evaluated_at"] = iso_str
            item_copy["snapshot_date"] = date_str
            docs.append(item_copy)

        mongo_client.connect()
        inserted_count = 0

        if mongo_client.db is not None:
            try:
                res = await mongo_client.db["repo_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} repo health evaluation snapshots to Async MongoDB.")
            except Exception as e:
                logger.warning(f"Async Mongo insert error: {e}")

        if inserted_count == 0 and mongo_client.sync_db is not None:
            try:
                res = mongo_client.sync_db["repo_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} repo health evaluation snapshots to Sync MongoDB.")
            except Exception as e:
                logger.warning(f"Sync Mongo insert error: {e}")

        return inserted_count

    @classmethod
    async def save_language_health_evaluations(cls, evaluations: List[Dict[str, Any]]) -> int:
        """Lưu danh sách kết quả đánh giá Language Health vào MongoDB Atlas kèm timestamp lịch sử."""
        if not evaluations:
            return 0
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        iso_str = now_utc.isoformat()
        date_str = now_utc.strftime("%Y-%m-%d")

        docs = []
        for eval_item in evaluations:
            item_copy = dict(eval_item)
            item_copy["evaluated_at"] = iso_str
            item_copy["snapshot_date"] = date_str
            docs.append(item_copy)

        mongo_client.connect()
        inserted_count = 0

        if mongo_client.db is not None:
            try:
                res = await mongo_client.db["language_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} language health evaluation snapshots to Async MongoDB.")
            except Exception as e:
                logger.warning(f"Async Mongo insert error: {e}")

        if inserted_count == 0 and mongo_client.sync_db is not None:
            try:
                res = mongo_client.sync_db["language_health_evaluations"].insert_many(docs)
                inserted_count = len(res.inserted_ids)
                logger.info(f"Saved {inserted_count} language health evaluation snapshots to Sync MongoDB.")
            except Exception as e:
                logger.warning(f"Sync Mongo insert error: {e}")

        return inserted_count

    @classmethod
    async def save_model_performance_log(cls, log_entry: Dict[str, Any]) -> bool:
        """Lưu nhật ký đánh giá hiệu năng mô hình (Model Performance Log) vào MongoDB Atlas."""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc)
        log_copy = dict(log_entry)
        if "timestamp" not in log_copy:
            log_copy["timestamp"] = now_utc.isoformat()

        mongo_client.connect()
        saved = False

        if mongo_client.db is not None:
            try:
                await mongo_client.db["model_performance_logs"].insert_one(log_copy)
                saved = True
                logger.info(f"Saved model performance log to Async MongoDB.")
            except Exception as e:
                logger.warning(f"Async Mongo insert error for performance log: {e}")

        if not saved and mongo_client.sync_db is not None:
            try:
                mongo_client.sync_db["model_performance_logs"].insert_one(log_copy)
                saved = True
                logger.info(f"Saved model performance log to Sync MongoDB.")
            except Exception as e:
                logger.warning(f"Sync Mongo insert error for performance log: {e}")

        return saved

    @classmethod
    async def get_repository_health_history(cls, repo_name: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Truy vấn lịch sử đánh giá điểm sức khỏe của 1 repo để vẽ biểu đồ."""
        history = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["repo_health_evaluations"].find(
                    {"repository": repo_name}
                ).sort("evaluated_at", -1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Async Mongo search error: {e}")

        if not history and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["repo_health_evaluations"].find(
                    {"repository": repo_name}
                ).sort("evaluated_at", -1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Sync Mongo search error: {e}")

        # Re-sort in ascending chronological order for frontend charts
        history.reverse()
        return history

    @classmethod
    async def get_language_health_history(cls, language: str, limit: int = 30) -> List[Dict[str, Any]]:
        """Truy vấn lịch sử điểm sức khỏe & chỉ số của 1 ngôn ngữ lập trình để vẽ biểu đồ."""
        history = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["language_health_evaluations"].find(
                    {"language": language}
                ).sort("evaluated_at", -1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Async Mongo search error: {e}")

        if not history and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["language_health_evaluations"].find(
                    {"language": language}
                ).sort("evaluated_at", -1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    history.append(doc)
            except Exception as e:
                logger.warning(f"Sync Mongo search error: {e}")

        history.reverse()
        return history

    @classmethod
    async def get_latest_model_performance_logs(cls, limit: int = 10) -> List[Dict[str, Any]]:
        """Truy vấn các nhật ký hiệu năng & cảnh báo sụt giảm mô hình mới nhất."""
        logs = []
        mongo_client.connect()

        if mongo_client.db is not None:
            try:
                cursor = mongo_client.db["model_performance_logs"].find({}).sort("timestamp", -1).limit(limit)
                async for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    logs.append(doc)
            except Exception as e:
                logger.warning(f"Async Mongo search error: {e}")

        if not logs and mongo_client.sync_db is not None:
            try:
                cursor = mongo_client.sync_db["model_performance_logs"].find({}).sort("timestamp", -1).limit(limit)
                for doc in cursor:
                    doc["_id"] = str(doc.get("_id"))
                    logs.append(doc)
            except Exception as e:
                logger.warning(f"Sync Mongo search error: {e}")

        return logs

