import logging
import asyncio
import random
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.crawl_config import CrawlConfigManager
from app.services.pipelines.crawler_pipeline import CrawlerPipeline
from app.services.pipelines.repo_updater_pipeline import RepoUpdaterPipeline
from app.core_models.data.db_loader import DatabaseDataLoader
from app.core_models.health.repository_health import RepositoryHealthModel
from app.core_models.health.language_health import LanguageHealthModel
from app.core_models.persistence.model_manager import ModelManager

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def scheduled_crawl_job():
    """
    Job chạy định kỳ thu thập dữ liệu GitHub repositories
    và cập nhật tự động vào MongoDB Atlas.
    """
    queries = CrawlConfigManager.get_queries()
    sort_options = CrawlConfigManager.get_sort_options()
    max_repos = CrawlConfigManager.get_max_repos()
    page_max = CrawlConfigManager.get_random_page_max()

    selected_query = random.choice(queries)
    selected_sort = random.choice(sort_options)
    random_page = random.randint(1, max(1, page_max))
    
    msg = f"[{datetime.now()}] Triggering scheduled GitHub Crawl Job (MongoDB Mode | query='{selected_query}', sort='{selected_sort}', page={random_page}, max_repos={max_repos})..."
    print(msg)
    logger.info(msg)
    
    try:
        pipeline = CrawlerPipeline()
        results = await pipeline.execute(query=selected_query, max_repos=max_repos, page=random_page, sort=selected_sort)
        done_msg = f"[{datetime.now()}] Scheduled Crawl Job finished successfully. Processed {len(results)} repositories into MongoDB Atlas."
        print(done_msg)
        logger.info(done_msg)
    except Exception as e:
        err_msg = f"Error during Scheduled Crawl Job: {e}"
        print(err_msg)
        logger.error(err_msg, exc_info=True)


async def scheduled_update_existing_repos_job():
    """
    Job chạy định kỳ để làm mới/cập nhật dữ liệu thời gian thực (stars, forks, issues, commits, PRs...)
    cho các repositories đã có trong Database MongoDB Atlas.
    Ưu tiên cập nhật các repositories lâu nhất chưa được đồng bộ.
    """
    batch_size = CrawlConfigManager.get_update_batch_size()
    msg = f"[{datetime.now()}] 🔄 Triggering scheduled EXISTING REPOSITORIES UPDATE JOB (batch_size={batch_size})..."
    print(msg)
    logger.info(msg)

    try:
        pipeline = RepoUpdaterPipeline()
        summary = await pipeline.execute(batch_size=batch_size)
        done_msg = f"[{datetime.now()}] ✅ Scheduled Existing Repos Update Job finished. Updated {summary.get('updated_count', 0)}/{summary.get('total_candidates', 0)} repositories."
        print(done_msg)
        logger.info(done_msg)
    except Exception as e:
        err_msg = f"Error during Scheduled Existing Repos Update Job: {e}"
        print(err_msg)
        logger.error(err_msg, exc_info=True)


async def scheduled_daily_train_job():
    """
    Cronjob hàng ngày (1 lần/ngày): 
    1. Cào đợt tổng hợp dữ liệu mới nhất từ GitHub API vào MongoDB Atlas.
    2. Nạp toàn bộ CSDL MongoDB Atlas để Huấn luyện / Đánh giá lại các Core ML Models.
    3. Lưu artifacts mô hình mới (.joblib) vào thư mục models/.
    """
    msg = f"[{datetime.now()}] 🚀 Triggering DAILY MODEL RETRAINING & DATA SYNC JOB..."
    print(msg)
    logger.info(msg)
    
    try:
        # 1. Quét cào dữ liệu mới nhất
        pipeline = CrawlerPipeline()
        queries = CrawlConfigManager.get_queries()
        max_queries = CrawlConfigManager.get_daily_retrain_max_queries()
        for q in queries[:max_queries]:
            await pipeline.execute(query=q, max_repos=5)
            
        # 2. Nạp dữ liệu từ MongoDB Atlas
        repos = await DatabaseDataLoader.get_all_repositories()
        lang_summaries = await DatabaseDataLoader.get_language_summary()
        
        # 3. Retrain & Lưu Artifacts mô hình với trọng số từ config
        repo_health_weights = CrawlConfigManager.get_repository_health_weights()
        lang_health_weights = CrawlConfigManager.get_language_health_weights()
        
        repo_health_model = RepositoryHealthModel(weights=repo_health_weights)
        lang_health_model = LanguageHealthModel(weights=lang_health_weights)
        
        for repo in repos:
            repo_health_model.evaluate(repo)
            
        for lang in lang_summaries:
            lang_health_model.evaluate(lang)
            
        model_manager = ModelManager()
        path1 = model_manager.save_model(repo_health_model, "repository_health", "repo_health_v1")
        path2 = model_manager.save_model(lang_health_model, "language_health", "lang_health_v1")
        
        done_msg = f"[{datetime.now()}] ✅ DAILY MODEL RETRAINING COMPLETED SUCCESSFULLY! Artifacts saved:\n   - {path1}\n   - {path2}"
        print(done_msg)
        logger.info(done_msg)
    except Exception as e:
        err_msg = f"Error during Daily Model Retraining Job: {e}"
        print(err_msg)
        logger.error(err_msg, exc_info=True)


def start_scheduler():
    """Khởi động APScheduler với Job Cào dữ liệu định kỳ, Job Cập nhật Repo cũ & Job Daily Retrain Models Hàng Ngày."""
    crawl_interval_minutes = CrawlConfigManager.get_interval_minutes()
    update_interval_minutes = CrawlConfigManager.get_update_interval_minutes()
    retrain_interval_days = CrawlConfigManager.get_model_retrain_interval_days()
    
    start_msg = (
        f"Starting APScheduler:\n"
        f"  - Periodic Crawl Job: Every {crawl_interval_minutes} mins\n"
        f"  - Periodic Existing Repos Update Job: Every {update_interval_minutes} mins\n"
        f"  - Daily Model Retrain Job: Every {retrain_interval_days} days"
    )
    print(start_msg)
    logger.info(start_msg)

    # 1. Job cào dữ liệu định kỳ (Tìm kiếm repo mới)
    scheduler.add_job(
        scheduled_crawl_job,
        trigger=IntervalTrigger(minutes=crawl_interval_minutes),
        id="github_crawler_job",
        name="GitHub Periodic Crawler Job",
        next_run_time=datetime.now(),
        replace_existing=True
    )

    # 2. Job cập nhật định kỳ cho các repo đã có trong Database
    scheduler.add_job(
        scheduled_update_existing_repos_job,
        trigger=IntervalTrigger(minutes=update_interval_minutes),
        id="github_update_existing_repos_job",
        name="GitHub Periodic Existing Repos Update Job",
        replace_existing=True
    )

    # 3. Job Retrain Models & Cập nhật dữ liệu HÀNG NGÀY (Cấu hình động từ JSON)
    scheduler.add_job(
        scheduled_daily_train_job,
        trigger=IntervalTrigger(days=retrain_interval_days),
        id="github_daily_train_job",
        name="GitHub Daily Model Retraining Job",
        replace_existing=True
    )

    scheduler.start()
    logger.info(f"APScheduler started successfully with 3 active cronjobs.")


def stop_scheduler():
    """Dừng APScheduler khi shutdown service."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
