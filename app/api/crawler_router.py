from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session
from typing import Optional
from app.db.database import get_db
from app.db import models
from app.services.pipelines.crawler_pipeline import CrawlerPipeline

router = APIRouter(prefix="/api/v1/crawler", tags=["Crawler"])

async def run_crawler_task(job_id: str, query: str, max_repos: int, db: Session):
    job = db.query(models.CrawlJob).filter(models.CrawlJob.id == job_id).first()
    if job:
        job.status = "RUNNING"
        db.commit()
        
    try:
        pipeline = CrawlerPipeline(db)
        results = await pipeline.execute(query=query, max_repos=max_repos)
        
        job = db.query(models.CrawlJob).filter(models.CrawlJob.id == job_id).first()
        if job:
            job.status = "SUCCESS"
            job.records_processed = len(results)
            db.commit()
    except Exception as e:
        job = db.query(models.CrawlJob).filter(models.CrawlJob.id == job_id).first()
        if job:
            job.status = "FAILED"
            job.error_message = str(e)
            db.commit()

@router.post("/jobs")
async def trigger_crawler(
    background_tasks: BackgroundTasks, 
    query: str = "stars:>500", 
    max_repos: int = 2,
    db: Session = Depends(get_db)
):
    """
    Trigger a multi-level crawler job
    """
    new_job = models.CrawlJob(status="PENDING")
    db.add(new_job)
    db.commit()
    db.refresh(new_job)
    
    # Run in background
    background_tasks.add_task(run_crawler_task, new_job.id, query, max_repos, db)
    
    return {"message": "Crawler job started", "job_id": new_job.id}

@router.get("/jobs/{job_id}")
def get_job_status(job_id: str, db: Session = Depends(get_db)):
    job = db.query(models.CrawlJob).filter(models.CrawlJob.id == job_id).first()
    if not job:
        return {"error": "Job not found"}
    return job
