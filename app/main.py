import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.core.config import settings
from app.api import crawler_router
from app.db.database import Base, engine
from app.jobs.scheduler import start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Initializing database...")
    Base.metadata.create_all(bind=engine)
    
    logger.info("Starting background scheduler...")
    scheduler = start_scheduler()
    
    yield
    # Shutdown
    logger.info("Shutting down...")
    scheduler.shutdown()

app = FastAPI(
    title=settings.PROJECT_NAME,
    lifespan=lifespan
)

# Include routers
app.include_router(crawler_router.router, prefix=settings.API_V1_STR)

@app.get("/")
def root():
    return {"message": "Welcome to DevRadar Github Crawler & AI Service"}
