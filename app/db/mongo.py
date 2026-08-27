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


mongo_client = MongoDBClient()
