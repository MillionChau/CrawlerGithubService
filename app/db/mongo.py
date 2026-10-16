import logging
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


mongo_client = MongoDBClient()
