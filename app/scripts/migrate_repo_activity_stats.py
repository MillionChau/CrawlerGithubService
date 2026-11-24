import asyncio
import logging
from datetime import datetime, timezone, timedelta
from pymongo import UpdateOne
from app.db.mongo import mongo_client
from app.services.data_cleaner import DataCleaner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migrate_repo_activity_stats")


async def run_migration():
    mongo_client.connect()
    db = mongo_client.db
    if db is None:
        logger.error("Could not connect to MongoDB Atlas!")
        return

    total_repos = await db["repositories"].count_documents({})
    logger.info(f"Starting activity_stats & maturity migration for {total_repos:,} repositories...")

    cursor = db["repositories"].find({}, {
        "_id": 1,
        "created_at": 1,
        "recent_commits": 1,
        "recent_pull_requests": 1
    })

    batch_size = 1000
    ops = []
    processed = 0
    updated_total = 0

    async for doc in cursor:
        repo_id = doc["_id"]
        created_at_val = doc.get("created_at")
        commits_list = doc.get("recent_commits") or []
        pulls_list = doc.get("recent_pull_requests") or []

        is_mature, act_stats = DataCleaner.compute_activity_and_maturity(
            commits_list, pulls_list, created_at_val
        )

        ops.append(
            UpdateOne(
                {"_id": repo_id},
                {"$set": {
                    "is_mature": is_mature,
                    "activity_stats": act_stats
                }}
            )
        )
        processed += 1

        if len(ops) >= batch_size:
            res = await db["repositories"].bulk_write(ops, ordered=False)
            updated_total += res.modified_count
            logger.info(f"Processed {processed:,}/{total_repos:,} repos (Updated: {updated_total:,})...")
            ops = []

    if ops:
        res = await db["repositories"].bulk_write(ops, ordered=False)
        updated_total += res.modified_count
        logger.info(f"Processed {processed:,}/{total_repos:,} repos (Updated: {updated_total:,})...")

    logger.info(f"SUCCESS: Activity stats migration complete! {updated_total:,} repos updated.")


if __name__ == "__main__":
    asyncio.run(run_migration())
