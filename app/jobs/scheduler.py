import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from app.core.config import settings
from app.services.crawler_service import CrawlerService
from app.db.database import SessionLocal
from app.db.models import CrawlJob

logger = logging.getLogger(__name__)

async def scheduled_crawl_task():
    logger.info("Running scheduled crawl task...")
    db = SessionLocal()
    try:
        # Create a job record
        job = CrawlJob(status="RUNNING")
        db.add(job)
        db.commit()
        db.refresh(job)
        
        await CrawlerService.run_crawl_job(db, job.id, query="stars:>1000")
    except Exception as e:
        logger.error(f"Scheduled task failed: {e}")
    finally:
        db.close()

def start_scheduler():
    scheduler = AsyncIOScheduler()
    
    # Run every X hours based on config
    scheduler.add_job(
        scheduled_crawl_task, 
        'interval', 
        hours=settings.CRAWL_INTERVAL_HOURS,
        id='github_crawl_job'
    )
    
    scheduler.start()
    logger.info("Scheduler started.")
    return scheduler
