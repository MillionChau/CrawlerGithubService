from contextlib import asynccontextmanager
from fastapi import FastAPI, BackgroundTasks
from app.db.mongo import mongo_client
from app.services.pipelines.crawler_pipeline import CrawlerPipeline
from app.jobs.scheduler import start_scheduler, stop_scheduler, scheduler, scheduled_crawl_job
from app.api.analytics import router as analytics_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    mongo_client.connect()
    start_scheduler()
    yield
    stop_scheduler()
    mongo_client.close()


app = FastAPI(
    title="DevRadar Crawler Github Service API",
    description="Microservice thu thập và phân tích dữ liệu GitHub repositories bằng MongoDB Atlas định kỳ.",
    version="1.0.0",
    lifespan=lifespan
)

app.include_router(analytics_router)


@app.get("/")
async def root():
    return {
        "service": "CrawlerGithubService",
        "database": "MongoDB Atlas",
        "status": "running",
        "docs": "/docs",
        "scheduler": "/scheduler/status"
    }


@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "CrawlerGithubService",
        "mongodb_connected": mongo_client.db is not None or mongo_client.sync_db is not None
    }


@app.get("/scheduler/status")
async def scheduler_status():
    jobs = []
    if scheduler.running:
        for job in scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": str(job.next_run_time)
            })
    return {
        "scheduler_running": scheduler.running,
        "jobs": jobs
    }


@app.post("/scheduler/trigger-now")
async def trigger_scheduler_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(scheduled_crawl_job)
    return {
        "status": "success",
        "message": "Scheduled crawl job triggered in background."
    }


@app.post("/crawl")
async def trigger_crawl(query: str = "stars:>10000", max_repos: int = 5):
    pipeline = CrawlerPipeline()
    results = await pipeline.execute(query=query, max_repos=max_repos)
    return {
        "status": "success",
        "processed_count": len(results),
        "data": results
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["app"])
