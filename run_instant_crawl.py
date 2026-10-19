import asyncio
import logging
import json
import os
from app.db.mongo import mongo_client
from app.services.pipelines.crawler_pipeline import CrawlerPipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


async def main():
    print("=" * 70)
    print("INSTANT CRAWL TEST - CHECKING MONGODB ATLAS DATA GROWTH")
    print("=" * 70)

    mongo_client.connect()

    try:
        count_mongo_before = 0
        if mongo_client.db is not None:
            count_mongo_before = await mongo_client.db["repositories"].count_documents({})
        elif mongo_client.sync_db is not None:
            count_mongo_before = mongo_client.sync_db["repositories"].count_documents({})

        print(f"\nSo luong Repositories trong MongoDB Atlas TRUOC KHI CRAWL: {count_mongo_before}")

        pipeline = CrawlerPipeline()
        print("\nDang gui request thu thap du lieu tu GitHub API (Query: 'stars:50..500', max_repos: 5)...")
        results = await pipeline.execute(query="stars:50..500", max_repos=5)
        
        count_mongo_after = 0
        if mongo_client.db is not None:
            count_mongo_after = await mongo_client.db["repositories"].count_documents({})
        elif mongo_client.sync_db is not None:
            count_mongo_after = mongo_client.sync_db["repositories"].count_documents({})

        print(f"\nSo luong Repositories trong MongoDB Atlas SAU KHI CRAWL: {count_mongo_after}")
        print(f"Da thu thap va xu ly thanh cong: {len(results)} repositories!")

        if os.path.exists("crawled_data.json"):
            with open("crawled_data.json", 'r', encoding='utf-8') as f:
                json_repos = json.load(f)
                print(f"Tong so repositories hien co trong local 'crawled_data.json': {len(json_repos)}")

    finally:
        mongo_client.close()

    print("\n" + "=" * 70)
    print("FINISHED INSTANT CRAWL TEST (MONGODB MODE).")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
