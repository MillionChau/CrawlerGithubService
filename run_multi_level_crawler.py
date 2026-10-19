import asyncio
import logging
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.db.database import SessionLocal, engine
from app.db import models
from app.db.mongo import mongo_client
from app.services.pipelines.crawler_pipeline import CrawlerPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_multi_level_demo():
    logger.info("Initializing database schema...")
    models.Base.metadata.create_all(bind=engine)
    
    # Kết nối MongoDB Atlas khi chạy script
    mongo_client.connect()
    
    logger.info("Starting Multi-Level Crawler Demo...")
    db = SessionLocal()
    try:
        pipeline = CrawlerPipeline(db)
        # Fetch top 2 trending repositories
        results = await pipeline.execute(query="stars:>50000", max_repos=2)
        
        logger.info(f"Multi-Level Pipeline completed. Processed {len(results)} repositories.")
        
        # Save to JSON
        output_file = os.path.join(os.path.dirname(__file__), "crawled_data.json")
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=4)
        logger.info(f"Successfully saved demo data to {output_file}")
        
        logger.info("Check crawler.db (SQLite) and MongoDB Atlas to see the populated data.")
    finally:
        db.close()
        mongo_client.close()


if __name__ == "__main__":
    asyncio.run(run_multi_level_demo())
