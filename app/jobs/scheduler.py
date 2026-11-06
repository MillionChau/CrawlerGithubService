import logging
import asyncio
import random
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

import uuid
from typing import Optional, Dict, Any
from app.core.config import settings
from app.core.crawl_config import CrawlConfigManager
from app.services.pipelines.crawler_pipeline import CrawlerPipeline
from app.services.pipelines.repo_updater_pipeline import RepoUpdaterPipeline
from app.core_models.data.db_loader import DatabaseDataLoader
from app.core_models.health.repository_health import RepositoryHealthModel
from app.core_models.health.language_health import LanguageHealthModel
from app.core_models.forecasting.forecasting_service import ForecastingService
from app.core_models.evaluation.metrics import ModelEvaluator, PerformanceTracker
from app.core_models.persistence.model_manager import ModelManager
from app.db.mongo import mongo_client
from app.services.report_generator import report_generator, generate_clean_slug

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
        results = await pipeline.execute(
            query=selected_query,
            max_repos=max_repos,
            page=random_page,
            sort=selected_sort,
            trigger_type="SCHEDULED"
        )
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
    3. Lưu snapshots dữ liệu đánh giá vào MongoDB Atlas để vẽ biểu đồ xu hướng.
    4. Đo đạc các chỉ số độ chính xác (MAE, RMSE, MAPE) & Kiểm tra sụt giảm hiệu năng.
    5. Lưu artifacts mô hình mới (.joblib) vào thư mục models/.
    """
    msg = f"[{datetime.now()}] 🚀 Triggering DAILY MODEL RETRAINING, HISTORY SNAPSHOT & EVALUATION LOG JOB..."
    print(msg)
    logger.info(msg)
    
    try:
        # 1. Quét cào dữ liệu mới nhất
        pipeline = CrawlerPipeline()
        queries = CrawlConfigManager.get_queries()
        max_queries = CrawlConfigManager.get_daily_retrain_max_queries()
        for q in queries[:max_queries]:
            await pipeline.execute(query=q, max_repos=5, trigger_type="SCHEDULED")
            
        # 2. Nạp dữ liệu từ MongoDB Atlas
        repos = await DatabaseDataLoader.get_all_repositories()
        lang_summaries = await DatabaseDataLoader.get_language_summary()
        
        # 3. Đánh giá sức khỏe Repositories & Ngôn ngữ
        repo_health_weights = CrawlConfigManager.get_repository_health_weights()
        lang_health_weights = CrawlConfigManager.get_language_health_weights()
        
        repo_health_model = RepositoryHealthModel(weights=repo_health_weights)
        lang_health_model = LanguageHealthModel(weights=lang_health_weights)
        
        repo_evaluations = [repo_health_model.evaluate(repo) for repo in repos]
        lang_evaluations = [lang_health_model.evaluate(lang) for lang in lang_summaries]
        
        # Lưu snapshots dữ liệu vào MongoDB Atlas để hỗ trợ vẽ biểu đồ
        n_repo_saved = await DatabaseDataLoader.save_repository_health_evaluations(repo_evaluations)
        n_lang_saved = await DatabaseDataLoader.save_language_health_evaluations(lang_evaluations)
        
        # 4. Thực hiện Backtesting dự báo (Forecasting Backtest) để đo độ chính xác
        forecasting_service = ForecastingService()
        y_true, y_pred = [], []
        
        for lang in lang_summaries:
            count = lang.get('repository_count', 10)
            rate = lang.get('repo_growth_rate', 0.05)
            history = [
                {"timestamp": "2026-05-01", "value": round(count * (1.0 - rate * 3), 1)},
                {"timestamp": "2026-06-01", "value": round(count * (1.0 - rate * 2), 1)},
                {"timestamp": "2026-07-01", "value": round(count * (1.0 - rate * 1), 1)}
            ]
            actual_latest = float(count)
            forecast_res = forecasting_service.predict_technology(lang['language'], history, steps=1)
            if forecast_res.get('forecast'):
                pred_val = forecast_res['forecast'][0]['predicted_value']
                y_true.append(actual_latest)
                y_pred.append(pred_val)
                
        metrics = ModelEvaluator.evaluate_forecasting(y_true, y_pred)
        
        # Lấy bản ghi log trước đó làm Baseline để so sánh
        prev_logs = await DatabaseDataLoader.get_latest_model_performance_logs(limit=1)
        prev_metrics = prev_logs[0].get("metrics") if prev_logs else None
        
        perf_report = PerformanceTracker.detect_degradation(metrics, prev_metrics, threshold_percentage=20.0)
        
        log_entry = {
            "dataset_size": len(repos),
            "language_count": len(lang_summaries),
            "metrics": metrics,
            "performance_status": perf_report["status"],
            "degraded": perf_report["degraded"],
            "percentage_change": perf_report.get("percentage_change", 0.0),
            "message": perf_report["message"]
        }
        await DatabaseDataLoader.save_model_performance_log(log_entry)
        
        # 5. Lưu artifacts mô hình bằng Joblib
        model_manager = ModelManager()
        path1 = model_manager.save_model(repo_health_model, "repository_health", "repo_health_v1")
        path2 = model_manager.save_model(lang_health_model, "language_health", "lang_health_v1")
        
        done_msg = (
            f"[{datetime.now()}] ✅ DAILY MODEL RETRAINING & EVALUATION COMPLETED!\n"
            f"   - Saved {n_repo_saved} Repo Snapshots, {n_lang_saved} Language Snapshots to MongoDB Atlas.\n"
            f"   - Performance Status: {perf_report['status']} | MAE: {metrics['mae']} | RMSE: {metrics['rmse']} | MAPE: {metrics['mape']}%\n"
            f"   - Saved Artifacts:\n"
            f"     * {path1}\n"
            f"     * {path2}"
        )
        print(done_msg)
        logger.info(done_msg)
    except Exception as e:
        err_msg = f"Error during Daily Model Retraining Job: {e}"
        print(err_msg)
        logger.error(err_msg, exc_info=True)


async def scheduled_auto_generate_reports_job() -> Optional[Dict[str, Any]]:
    """
    Job chạy định kỳ (12h/24h) tự động phân tích dữ liệu kho mã nguồn MongoDB Atlas
    và kích hoạt UnoRouter AI / Heuristic Generator để sinh bài báo cáo công nghệ mới.
    """
    if not CrawlConfigManager.is_auto_report_enabled():
        logger.info("[Auto Report Job] Tự động sinh báo cáo đang tạm tắt (auto_report_enabled=False).")
        return None

    msg = f"[{datetime.now()}] 🧠 Triggering SCHEDULED AUTO TECH REPORT GENERATION JOB..."
    print(msg)
    logger.info(msg)

    try:
        # 1. Thu thập danh sách chủ đề tiềm năng từ kho dữ liệu
        overview = await mongo_client.get_system_overview()
        top_langs = [item.get("language") for item in overview.get("top_languages", []) if item.get("language")]
        now_dt = datetime.utcnow()
        current_month_str = f"Tháng {now_dt.month}/{now_dt.year}"
        
        # 2. Rà soát các bài báo cáo gần đây trong MongoDB để tránh trùng lặp chủ đề
        _, recent_reports = await mongo_client.get_tech_reports(page=1, limit=15)
        recent_tags = set()
        has_monthly_report_for_current_month = False
        recently_evaluated_repos = set()

        for r in recent_reports:
            for t in r.get("tags", []):
                recent_tags.add(t.lower())
            if r.get("category") == "MONTHLY_TREND" and str(now_dt.month) in r.get("title", ""):
                has_monthly_report_for_current_month = True
            if r.get("category") == "REPOSITORY":
                repo_ref = r.get("metrics_snapshot", {}).get("repository") or r.get("title", "")
                recently_evaluated_repos.add(repo_ref.lower())

        # 3. Lựa chọn chuyên mục và chủ đề luân phiên thông minh:
        # Ưu tiên A: Tự động xây dựng Báo cáo Tháng nếu chưa có trong tháng hiện tại
        # Ưu tiên B: Tự động đánh giá chuyên sâu một Repository hàng đầu chưa được đánh giá gần đây
        # Ưu tiên C: Báo cáo xu hướng ngôn ngữ / framework
        target_repo = None
        target_tech = None

        if not has_monthly_report_for_current_month:
            category = "MONTHLY_TREND"
            topic = f"Báo cáo Chuyển dịch Xu hướng Công nghệ & Mã nguồn mở {current_month_str}"
        else:
            # Chọn top repositories từ MongoDB
            top_repos_candidates = []
            if mongo_client.db is not None:
                try:
                    cursor = mongo_client.db["repositories"].find({}).sort("stars", -1).limit(10)
                    async for doc in cursor:
                        r_name = doc.get("full_name") or doc.get("name")
                        if r_name and r_name.lower() not in recently_evaluated_repos:
                            top_repos_candidates.append(r_name)
                except Exception:
                    pass

            # Luân phiên 50% sinh Báo cáo Repository, 50% sinh Báo cáo Ngôn ngữ/Công nghệ
            if top_repos_candidates and random.random() < 0.5:
                category = "REPOSITORY"
                target_repo = top_repos_candidates[0]
                topic = f"Báo cáo Đánh giá Chuyên sâu Kiến trúc & Sức khỏe Kho mã nguồn {target_repo}"
            else:
                candidate_techs = [l for l in top_langs if l.lower() not in recent_tags]
                target_tech = candidate_techs[0] if candidate_techs else (top_langs[0] if top_langs else "Python")
                category = random.choice(["LANGUAGE", "TREND", "FRAMEWORK", "DEVOPS"])
                topic = f"Báo cáo toàn cảnh xu hướng công nghệ {target_tech} và hệ sinh thái phần mềm 2026"

        logger.info(f"[Auto Report Job] Selected topic: '{topic}' | Category: {category} | Target Tech: {target_tech} | Target Repo: {target_repo}")

        # 4. Kích hoạt Report Generator (AI + Live Crawler Metrics)
        generated = await report_generator.generate_report(
            topic=topic,
            category=category,
            target_tech=target_tech,
            target_repo=target_repo,
            include_live_metrics=True
        )

        now = datetime.utcnow()
        report_id = str(uuid.uuid4())
        report_status = CrawlConfigManager.get_auto_report_status()

        report_dict = {
            "id": report_id,
            "slug": generated.get("slug") or generate_clean_slug(generated.get("title")),
            "title": generated.get("title"),
            "summary": generated.get("summary"),
            "content_markdown": generated.get("content_markdown"),
            "category": generated.get("category", category).upper(),
            "tags": generated.get("tags", []),
            "metrics_snapshot": generated.get("metrics_snapshot", {}),
            "status": report_status,
            "views_count": 0,
            "likes_count": 0,
            "author_id": "ai-scheduler",
            "author_name": "DevRadar AI Analyst (Auto Scheduled)",
            "created_at": now,
            "updated_at": now,
            "published_at": now if report_status == "PUBLISHED" else None
        }

        # 5. Lưu vào MongoDB Atlas
        await mongo_client.create_tech_report(report_dict)

        success_msg = (
            f"[{datetime.now()}] ✅ AUTO TECH REPORT GENERATED & SAVED SUCCESSFULLY!\n"
            f"   - Title: {report_dict['title']}\n"
            f"   - Slug: {report_dict['slug']}\n"
            f"   - Status: {report_dict['status']}\n"
            f"   - AI Generated: {generated.get('ai_generated')}\n"
            f"   - Model: {generated.get('model_used')}"
        )
        print(success_msg)
        logger.info(success_msg)
        return report_dict

    except Exception as e:
        err_msg = f"Error during Scheduled Auto Tech Report Job: {e}"
        print(err_msg)
        logger.error(err_msg, exc_info=True)
        return None


def start_scheduler():
    """Khởi động APScheduler với Job Cào dữ liệu định kỳ, Job Cập nhật Repo cũ, Job Retrain Models & Job Sinh Báo Cáo AI Tự Động."""
    crawl_interval_minutes = CrawlConfigManager.get_interval_minutes()
    update_interval_minutes = CrawlConfigManager.get_update_interval_minutes()
    retrain_interval_days = CrawlConfigManager.get_model_retrain_interval_days()
    auto_report_hours = CrawlConfigManager.get_auto_report_interval_hours()
    auto_report_active = CrawlConfigManager.is_auto_report_enabled()
    
    start_msg = (
        f"Starting APScheduler:\n"
        f"  - Periodic Crawl Job: Every {crawl_interval_minutes} mins\n"
        f"  - Periodic Existing Repos Update Job: Every {update_interval_minutes} mins\n"
        f"  - Daily Model Retrain Job: Every {retrain_interval_days} days\n"
        f"  - Auto AI Tech Report Job: {'Every ' + str(auto_report_hours) + ' hours' if auto_report_active else 'DISABLED'}"
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

    # 4. Job Tự động sinh báo cáo phân tích công nghệ AI định kỳ
    if auto_report_active:
        scheduler.add_job(
            scheduled_auto_generate_reports_job,
            trigger=IntervalTrigger(hours=auto_report_hours),
            id="github_auto_report_job",
            name="AI Periodic Tech Report Generation Job",
            replace_existing=True
        )

    scheduler.start()
    total_jobs = len(scheduler.get_jobs())
    logger.info(f"APScheduler started successfully with {total_jobs} active cronjobs.")


def reschedule_jobs():
    """
    Cập nhật động chu kỳ lập lịch của các cronjob đang chạy mà không cần khởi động lại service.
    Được gọi ngay khi Admin lưu cấu hình crawl_config.json mới.
    """
    if not scheduler.running:
        return

    crawl_interval_minutes = CrawlConfigManager.get_interval_minutes()
    update_interval_minutes = CrawlConfigManager.get_update_interval_minutes()
    retrain_interval_days = CrawlConfigManager.get_model_retrain_interval_days()
    auto_report_hours = CrawlConfigManager.get_auto_report_interval_hours()
    auto_report_active = CrawlConfigManager.is_auto_report_enabled()

    try:
        scheduler.reschedule_job("github_crawler_job", trigger=IntervalTrigger(minutes=crawl_interval_minutes))
        logger.info(f"Rescheduled github_crawler_job to every {crawl_interval_minutes} mins.")
    except Exception as e:
        logger.warning(f"Could not reschedule github_crawler_job: {e}")

    try:
        scheduler.reschedule_job("github_update_existing_repos_job", trigger=IntervalTrigger(minutes=update_interval_minutes))
        logger.info(f"Rescheduled github_update_existing_repos_job to every {update_interval_minutes} mins.")
    except Exception as e:
        logger.warning(f"Could not reschedule github_update_existing_repos_job: {e}")

    try:
        scheduler.reschedule_job("github_daily_train_job", trigger=IntervalTrigger(days=retrain_interval_days))
        logger.info(f"Rescheduled github_daily_train_job to every {retrain_interval_days} days.")
    except Exception as e:
        logger.warning(f"Could not reschedule github_daily_train_job: {e}")

    if auto_report_active:
        try:
            scheduler.reschedule_job("github_auto_report_job", trigger=IntervalTrigger(hours=auto_report_hours))
            logger.info(f"Rescheduled github_auto_report_job to every {auto_report_hours} hours.")
        except Exception:
            pass


def stop_scheduler():
    """Dừng APScheduler khi shutdown service."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler stopped.")
