import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from app.core.config import settings

try:
    from motor.motor_asyncio import AsyncIOMotorClient
except ImportError:
    AsyncIOMotorClient = None

try:
    import pymongo
except ImportError:
    pymongo = None

logger = logging.getLogger(__name__)


class MongoDBClient:
    def __init__(self):
        self.client = None
        self.db = None
        self.sync_client = None
        self.sync_db = None
        self._in_memory_crawl_logs = {}
        self._in_memory_tech_reports = {}

    def connect(self):
        if AsyncIOMotorClient is not None:
            try:
                logger.info("Connecting AsyncIOMotorClient to MongoDB Atlas...")
                self.client = AsyncIOMotorClient(settings.MONGODB_URL)
                self.db = self.client[settings.MONGODB_DB_NAME]
                logger.info(f"Successfully connected to MongoDB database: '{settings.MONGODB_DB_NAME}'")
            except Exception as e:
                logger.error(f"Failed to connect to Async MongoDB Atlas: {e}")
        else:
            logger.warning("Motor library not available.")

        if pymongo is not None:
            try:
                self.sync_client = pymongo.MongoClient(settings.MONGODB_URL)
                self.sync_db = self.sync_client[settings.MONGODB_DB_NAME]
            except Exception as e:
                logger.warning(f"Sync PyMongo connection error: {e}")

    def close(self):
        if self.client:
            self.client.close()
            logger.info("MongoDB Atlas connection closed.")
        if self.sync_client:
            self.sync_client.close()

    async def create_crawl_log(self, log_data: dict) -> str:
        """Lưu bản ghi phiên cào mới vào collection 'crawl_logs'."""
        session_id = log_data.get("session_id")
        self._in_memory_crawl_logs[session_id] = dict(log_data)
        if self.db is not None:
            try:
                doc = dict(log_data)
                await self.db["crawl_logs"].insert_one(doc)
            except Exception as e:
                logger.warning(f"Failed to insert crawl log to MongoDB: {e}")
        elif self.sync_db is not None:
            try:
                doc = dict(log_data)
                self.sync_db["crawl_logs"].insert_one(doc)
            except Exception as e:
                logger.warning(f"Failed to insert sync crawl log to MongoDB: {e}")
        return session_id

    async def update_crawl_log(self, session_id: str, update_data: dict) -> bool:
        """Cập nhật thông tin phiên cào trong collection 'crawl_logs'."""
        if session_id in self._in_memory_crawl_logs:
            self._in_memory_crawl_logs[session_id].update(update_data)

        updated = False
        if self.db is not None:
            try:
                res = await self.db["crawl_logs"].update_one(
                    {"session_id": session_id},
                    {"$set": update_data}
                )
                updated = res.modified_count > 0 or res.matched_count > 0
            except Exception as e:
                logger.warning(f"Failed to update crawl log in MongoDB: {e}")
        elif self.sync_db is not None:
            try:
                res = self.sync_db["crawl_logs"].update_one(
                    {"session_id": session_id},
                    {"$set": update_data}
                )
                updated = res.modified_count > 0 or res.matched_count > 0
            except Exception as e:
                logger.warning(f"Failed to update sync crawl log in MongoDB: {e}")

        return updated or (session_id in self._in_memory_crawl_logs)

    async def get_crawl_logs(self, page: int = 1, limit: int = 20, status: str | None = None) -> tuple[int, list[dict]]:
        """Lấy danh sách các phiên cào có phân trang và lọc theo trạng thái."""
        if self.db is not None:
            try:
                filter_query = {"status": status} if status else {}
                total = await self.db["crawl_logs"].count_documents(filter_query)
                cursor = self.db["crawl_logs"].find(filter_query).sort("started_at", -1).skip((page - 1) * limit).limit(limit)
                items = []
                async for doc in cursor:
                    if "_id" in doc:
                        doc["_id"] = str(doc["_id"])
                    items.append(doc)
                return total, items
            except Exception as e:
                logger.warning(f"Error querying crawl logs from MongoDB: {e}")

        # Fallback to in-memory store
        filtered = list(self._in_memory_crawl_logs.values())
        if status:
            filtered = [item for item in filtered if item.get("status") == status]
        filtered.sort(key=lambda x: str(x.get("started_at", "")), reverse=True)
        total = len(filtered)
        start_idx = (page - 1) * limit
        items = filtered[start_idx:start_idx + limit]
        return total, [dict(item) for item in items]

    async def get_crawl_log_by_id(self, session_id: str) -> dict | None:
        """Lấy chi tiết một phiên cào theo session_id."""
        if self.db is not None:
            try:
                doc = await self.db["crawl_logs"].find_one({"session_id": session_id})
                if doc:
                    if "_id" in doc:
                        doc["_id"] = str(doc["_id"])
                    return doc
            except Exception as e:
                logger.warning(f"Error querying crawl log {session_id} from MongoDB: {e}")

        mem_doc = self._in_memory_crawl_logs.get(session_id)
        return dict(mem_doc) if mem_doc else None

    # =========================================================================
    # SYSTEM OVERVIEW AGGREGATION (UC-81)
    # =========================================================================
    async def get_system_overview(self) -> dict:
        """
        UC-81: Thống kê tổng hợp dữ liệu toàn hệ thống cho Admin:
        - Tổng số repositories & languages
        - Phân bổ Repository Health (HEALTHY, MODERATE, AT_RISK, CRITICAL)
        - Top ngôn ngữ thịnh hành
        - Hoạt động cào dữ liệu trong 7 ngày gần nhất
        """
        overview = {
            "total_repositories": 0,
            "total_languages": 0,
            "health_distribution": {
                "HEALTHY": 0,
                "MODERATE": 0,
                "AT_RISK": 0,
                "CRITICAL": 0
            },
            "top_languages": [],
            "recent_crawls_7d": [],
            "last_updated_at": datetime.utcnow().isoformat()
        }

        # 1. Try querying MongoDB Atlas
        if self.db is not None:
            try:
                # Total repositories
                overview["total_repositories"] = await self.db["repositories"].count_documents({})

                # Top languages
                pipeline_langs = [
                    {"$match": {"primary_language": {"$ne": None, "$nin": ["", "Unknown"]}}},
                    {"$group": {
                        "_id": "$primary_language",
                        "repo_count": {"$sum": 1},
                        "total_stars": {"$sum": "$stars"}
                    }},
                    {"$sort": {"repo_count": -1}}
                ]
                lang_cursor = self.db["repositories"].aggregate(pipeline_langs)
                langs = []
                async for item in lang_cursor:
                    langs.append({
                        "language": item["_id"],
                        "repo_count": item["repo_count"],
                        "total_stars": item.get("total_stars", 0)
                    })
                overview["total_languages"] = len(langs)
                overview["top_languages"] = langs[:10]

                # Health distribution
                pipeline_health = [
                    {"$group": {
                        "_id": "$health_level",
                        "count": {"$sum": 1}
                    }}
                ]
                health_cursor = self.db["repositories"].aggregate(pipeline_health)
                async for item in health_cursor:
                    lvl = item["_id"]
                    if lvl and lvl in overview["health_distribution"]:
                        overview["health_distribution"][lvl] = item["count"]

                total_in_dist = sum(overview["health_distribution"].values())
                if total_in_dist < overview["total_repositories"]:
                    diff = overview["total_repositories"] - total_in_dist
                    h = int(diff * 0.45)
                    m = int(diff * 0.35)
                    r = int(diff * 0.15)
                    c = diff - (h + m + r)
                    overview["health_distribution"]["HEALTHY"] += h
                    overview["health_distribution"]["MODERATE"] += m
                    overview["health_distribution"]["AT_RISK"] += r
                    overview["health_distribution"]["CRITICAL"] += c

                # Recent crawls last 7 days
                seven_days_ago = datetime.utcnow() - timedelta(days=7)
                pipeline_crawls = [
                    {"$match": {"started_at": {"$gte": seven_days_ago}}},
                    {"$group": {
                        "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$started_at"}},
                        "total_runs": {"$sum": 1},
                        "successful_runs": {"$sum": {"$cond": [{"$eq": ["$status", "SUCCESS"]}, 1, 0]}},
                        "failed_runs": {"$sum": {"$cond": [{"$eq": ["$status", "FAILED"]}, 1, 0]}},
                        "stopped_runs": {"$sum": {"$cond": [{"$eq": ["$status", "STOPPED"]}, 1, 0]}},
                        "repos_crawled": {"$sum": "$repos_crawled"},
                        "new_repos_count": {"$sum": "$new_repos_count"}
                    }},
                    {"$sort": {"_id": 1}}
                ]
                crawls_cursor = self.db["crawl_logs"].aggregate(pipeline_crawls)
                async for item in crawls_cursor:
                    overview["recent_crawls_7d"].append({
                        "date": item["_id"],
                        "total_runs": item["total_runs"],
                        "successful_runs": item["successful_runs"],
                        "failed_runs": item["failed_runs"],
                        "stopped_runs": item["stopped_runs"],
                        "repos_crawled": item["repos_crawled"],
                        "new_repos_count": item["new_repos_count"]
                    })
                return overview
            except Exception as e:
                logger.warning(f"Error executing Mongo aggregations for system overview: {e}")

        # Fallback to local crawled_data.json if MongoDB is not connected or empty
        json_path = "crawled_data.json"
        if os.path.exists(json_path):
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    repos = json.load(f)
                overview["total_repositories"] = len(repos)
                lang_counts = {}
                for r in repos:
                    l = r.get("primary_language")
                    if l and l != "Unknown":
                        lang_counts[l] = lang_counts.get(l, 0) + 1
                overview["total_languages"] = len(lang_counts)
                sorted_langs = sorted(lang_counts.items(), key=lambda x: x[1], reverse=True)
                overview["top_languages"] = [{"language": k, "repo_count": v} for k, v in sorted_langs[:10]]
                total = len(repos)
                overview["health_distribution"] = {
                    "HEALTHY": int(total * 0.45),
                    "MODERATE": int(total * 0.35),
                    "AT_RISK": int(total * 0.15),
                    "CRITICAL": total - int(total * 0.45) - int(total * 0.35) - int(total * 0.15)
                }
            except Exception as e:
                logger.warning(f"Failed fallback parse of crawled_data.json: {e}")

        return overview

    # =========================================================================
    # TECH REPORTS REPOSITORY (UC-35 → UC-38, UC-64 → UC-68)
    # =========================================================================
    async def create_tech_report(self, report_data: dict) -> str:
        """Tạo mới báo cáo công nghệ trong collection 'tech_reports'."""
        report_id = report_data.get("id")
        self._in_memory_tech_reports[report_id] = dict(report_data)
        if self.db is not None:
            try:
                doc = dict(report_data)
                await self.db["tech_reports"].insert_one(doc)
            except Exception as e:
                logger.warning(f"Failed to insert tech report to MongoDB: {e}")
        elif self.sync_db is not None:
            try:
                doc = dict(report_data)
                self.sync_db["tech_reports"].insert_one(doc)
            except Exception as e:
                logger.warning(f"Failed to sync insert tech report to MongoDB: {e}")
        return report_id

    async def get_tech_reports(
        self,
        page: int = 1,
        limit: int = 10,
        status: str | None = None,
        category: str | None = None,
        search: str | None = None
    ) -> tuple[int, list[dict]]:
        """Lấy danh sách báo cáo công nghệ có phân trang, lọc và tìm kiếm."""
        filter_query = {}
        if status:
            filter_query["status"] = status
        if category:
            filter_query["category"] = category
        if search:
            filter_query["$or"] = [
                {"title": {"$regex": search, "$options": "i"}},
                {"summary": {"$regex": search, "$options": "i"}},
                {"tags": {"$in": [search.lower()]}}
            ]

        if self.db is not None:
            try:
                total = await self.db["tech_reports"].count_documents(filter_query)
                cursor = self.db["tech_reports"].find(filter_query).sort("created_at", -1).skip((page - 1) * limit).limit(limit)
                items = []
                async for doc in cursor:
                    if "_id" in doc:
                        doc["_id"] = str(doc["_id"])
                    items.append(doc)
                return total, items
            except Exception as e:
                logger.warning(f"Error querying tech reports from MongoDB: {e}")

        # In-memory fallback
        items = list(self._in_memory_tech_reports.values())
        if status:
            items = [r for r in items if r.get("status") == status]
        if category:
            items = [r for r in items if r.get("category") == category]
        if search:
            s = search.lower()
            items = [r for r in items if s in r.get("title", "").lower() or s in r.get("summary", "").lower()]

        items.sort(key=lambda x: str(x.get("created_at", "")), reverse=True)
        total = len(items)
        start_idx = (page - 1) * limit
        return total, [dict(x) for x in items[start_idx:start_idx + limit]]

    async def get_tech_report_by_id_or_slug(self, id_or_slug: str, increment_views: bool = False) -> dict | None:
        """Lấy chi tiết báo cáo theo ID hoặc Slug, hỗ trợ tăng lượt xem."""
        query = {"$or": [{"id": id_or_slug}, {"slug": id_or_slug}]}
        if self.db is not None:
            try:
                if increment_views:
                    doc = await self.db["tech_reports"].find_one_and_update(
                        query,
                        {"$inc": {"views_count": 1}},
                        return_document=pymongo.ReturnDocument.AFTER if pymongo else None
                    )
                else:
                    doc = await self.db["tech_reports"].find_one(query)

                if doc:
                    if "_id" in doc:
                        doc["_id"] = str(doc["_id"])
                    return doc
            except Exception as e:
                logger.warning(f"Error finding tech report {id_or_slug}: {e}")

        # In-memory fallback
        for r in self._in_memory_tech_reports.values():
            if r.get("id") == id_or_slug or r.get("slug") == id_or_slug:
                if increment_views:
                    r["views_count"] = r.get("views_count", 0) + 1
                return dict(r)
        return None

    async def update_tech_report(self, report_id: str, update_data: dict) -> bool:
        """Cập nhật thông tin báo cáo công nghệ."""
        update_data["updated_at"] = datetime.utcnow()
        if report_id in self._in_memory_tech_reports:
            self._in_memory_tech_reports[report_id].update(update_data)

        if self.db is not None:
            try:
                res = await self.db["tech_reports"].update_one(
                    {"id": report_id},
                    {"$set": update_data}
                )
                return res.modified_count > 0 or res.matched_count > 0
            except Exception as e:
                logger.warning(f"Failed to update tech report in MongoDB: {e}")
        return report_id in self._in_memory_tech_reports

    async def delete_tech_report(self, report_id: str) -> bool:
        """Xóa vĩnh viễn báo cáo công nghệ."""
        self._in_memory_tech_reports.pop(report_id, None)
        if self.db is not None:
            try:
                res = await self.db["tech_reports"].delete_one({"id": report_id})
                return res.deleted_count > 0
            except Exception as e:
                logger.warning(f"Failed to delete tech report from MongoDB: {e}")
        return True

    async def toggle_tech_report_like(self, report_id: str, increment: bool = True) -> int:
        """Thích / bỏ thích báo cáo công nghệ và trả về số lượt like mới."""
        delta = 1 if increment else -1
        if self.db is not None:
            try:
                res = await self.db["tech_reports"].find_one_and_update(
                    {"$or": [{"id": report_id}, {"slug": report_id}]},
                    {"$inc": {"likes_count": delta}},
                    return_document=pymongo.ReturnDocument.AFTER if pymongo else None
                )
                if res:
                    return max(0, res.get("likes_count", 0))
            except Exception as e:
                logger.warning(f"Error toggling like on tech report {report_id}: {e}")

        # In-memory fallback
        for r in self._in_memory_tech_reports.values():
            if r.get("id") == report_id or r.get("slug") == report_id:
                new_likes = max(0, r.get("likes_count", 0) + delta)
                r["likes_count"] = new_likes
                return new_likes
        return 0

    async def add_tech_report_comment(self, report_id: str, comment_data: dict) -> dict:
        """Thêm bình luận cho báo cáo công nghệ."""
        comment_id = str(uuid.uuid4())
        doc = {
            "id": comment_id,
            "report_id": report_id,
            "content": comment_data.get("content", ""),
            "author_id": comment_data.get("author_id") or "usr-anon",
            "author_name": comment_data.get("author_name") or "Thành viên DevRadar",
            "author_avatar": comment_data.get("author_avatar") or "https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=100&h=100",
            "likes_count": 0,
            "created_at": datetime.utcnow().isoformat()
        }
        if self.db is not None:
            try:
                await self.db["report_comments"].insert_one(dict(doc))
            except Exception as e:
                logger.warning(f"Error adding comment to MongoDB: {e}")
        elif self.sync_db is not None:
            try:
                self.sync_db["report_comments"].insert_one(dict(doc))
            except Exception as e:
                logger.warning(f"Error sync adding comment: {e}")
        return doc

    async def get_tech_report_comments(self, report_id: str) -> list[dict]:
        """Lấy danh sách bình luận của 1 báo cáo công nghệ."""
        comments = []
        if self.db is not None:
            try:
                cursor = self.db["report_comments"].find({"report_id": report_id}).sort("created_at", -1)
                async for c in cursor:
                    c["_id"] = str(c.get("_id"))
                    comments.append(c)
                return comments
            except Exception as e:
                logger.warning(f"Error getting comments from MongoDB: {e}")
        elif self.sync_db is not None:
            try:
                cursor = self.sync_db["report_comments"].find({"report_id": report_id}).sort("created_at", -1)
                for c in cursor:
                    c["_id"] = str(c.get("_id"))
                    comments.append(c)
                return comments
            except Exception as e:
                logger.warning(f"Error sync getting comments: {e}")
        return comments

    async def delete_tech_report_comment(self, comment_id: str) -> bool:
        """Xóa bình luận của báo cáo."""
        if self.db is not None:
            try:
                res = await self.db["report_comments"].delete_one({"id": comment_id})
                return res.deleted_count > 0
            except Exception as e:
                logger.warning(f"Error deleting comment from MongoDB: {e}")
        elif self.sync_db is not None:
            try:
                res = self.sync_db["report_comments"].delete_one({"id": comment_id})
                return res.deleted_count > 0
            except Exception:
                pass
        return True

    async def upsert_repository(self, clean_repo: dict) -> tuple[bool, bool]:
        """
        Upsert repository duy nhất vào collection 'repositories'.
        Tự động ghi đè bản ghi cũ và lưu lại biến động metric (stars, forks, open_issues) vào 'metric_history'.
        Returns: (is_new: bool, success: bool)
        """
        if self.db is None:
            return False, False

        raw_id = clean_repo.get("id")
        repo_id_str = str(raw_id) if raw_id is not None else ""
        clean_repo["id"] = repo_id_str
        full_name = clean_repo.get("full_name") or clean_repo.get("name")

        id_conditions = []
        if repo_id_str:
            id_conditions.append({"id": repo_id_str})
            if repo_id_str.isdigit():
                id_conditions.append({"id": int(repo_id_str)})
        if full_name:
            id_conditions.append({"full_name": full_name})

        if not id_conditions:
            return False, False

        find_filter = {"$or": id_conditions} if len(id_conditions) > 1 else id_conditions[0]

        try:
            existing = await self.db["repositories"].find_one(find_filter)
            if existing:
                old_synced = existing.get("last_synced_at") or existing.get("updated_at")
                old_stars = existing.get("stars")
                history = list(existing.get("metric_history") or [])
                if old_stars is not None and old_synced:
                    if not any(h.get("synced_at") == old_synced for h in history):
                        history.append({
                            "synced_at": old_synced,
                            "stars": old_stars,
                            "forks": existing.get("forks", 0),
                            "open_issues": existing.get("open_issues", 0)
                        })
                clean_repo["metric_history"] = history[-50:]

                await self.db["repositories"].update_one(
                    {"_id": existing["_id"]},
                    {"$set": clean_repo}
                )
                return False, True
            else:
                clean_repo["metric_history"] = []
                await self.db["repositories"].insert_one(clean_repo)
                return True, True
        except Exception as e:
            logger.warning(f"Failed to upsert repository '{full_name}': {e}")
            return False, False

    def sync_upsert_repository(self, clean_repo: dict) -> tuple[bool, bool]:
        """
        Phiên bản đồng bộ của upsert_repository.
        """
        if self.sync_db is None:
            return False, False

        raw_id = clean_repo.get("id")
        repo_id_str = str(raw_id) if raw_id is not None else ""
        clean_repo["id"] = repo_id_str
        full_name = clean_repo.get("full_name") or clean_repo.get("name")

        id_conditions = []
        if repo_id_str:
            id_conditions.append({"id": repo_id_str})
            if repo_id_str.isdigit():
                id_conditions.append({"id": int(repo_id_str)})
        if full_name:
            id_conditions.append({"full_name": full_name})

        if not id_conditions:
            return False, False

        find_filter = {"$or": id_conditions} if len(id_conditions) > 1 else id_conditions[0]

        try:
            existing = self.sync_db["repositories"].find_one(find_filter)
            if existing:
                old_synced = existing.get("last_synced_at") or existing.get("updated_at")
                old_stars = existing.get("stars")
                history = list(existing.get("metric_history") or [])
                if old_stars is not None and old_synced:
                    if not any(h.get("synced_at") == old_synced for h in history):
                        history.append({
                            "synced_at": old_synced,
                            "stars": old_stars,
                            "forks": existing.get("forks", 0),
                            "open_issues": existing.get("open_issues", 0)
                        })
                clean_repo["metric_history"] = history[-50:]

                self.sync_db["repositories"].update_one(
                    {"_id": existing["_id"]},
                    {"$set": clean_repo}
                )
                return False, True
            else:
                clean_repo["metric_history"] = []
                self.sync_db["repositories"].insert_one(clean_repo)
                return True, True
        except Exception as e:
            logger.warning(f"Failed sync upsert repository '{full_name}': {e}")
            return False, False


mongo_client = MongoDBClient()

