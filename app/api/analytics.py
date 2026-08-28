from fastapi import APIRouter, HTTPException, Query
from typing import Dict, Any, List, Optional
from pydantic import BaseModel

from app.core_models.health.repository_health import RepositoryHealthModel
from app.core_models.health.language_health import LanguageHealthModel
from app.core_models.trend.trend_analyzer import TechnologyTrendAnalyzer
from app.core_models.forecasting.forecasting_service import ForecastingService

router = APIRouter(prefix="/analytics", tags=["Analytics & Core Models"])

repo_health_model = RepositoryHealthModel()
lang_health_model = LanguageHealthModel()
trend_analyzer = TechnologyTrendAnalyzer()
forecasting_service = ForecastingService()


class RepoHealthRequest(BaseModel):
    full_name: str
    stars: int = 0
    forks: int = 0
    open_issues: int = 0
    closed_issues_30d: int = 5
    contributors_count: int = 1
    recent_commits_30d: int = 10
    days_since_last_push: int = 2
    star_growth_rate_30d: float = 0.05


class LanguageHealthRequest(BaseModel):
    language: str
    repository_count: int = 1000
    total_stars: int = 50000
    total_forks: int = 10000
    commit_activity_index: float = 75.0
    contributor_activity_index: float = 80.0
    repo_growth_rate: float = 0.05
    star_growth_rate: float = 0.08


class TrendAnalysisRequest(BaseModel):
    technology: str
    series_values: List[float]


class ForecastRequest(BaseModel):
    technology: str
    history_records: List[Dict[str, Any]]
    steps: int = 3


@router.post("/repository-health")
async def calculate_repository_health(request: RepoHealthRequest) -> Dict[str, Any]:
    """
    Tính toán chỉ số Repository Health (0-100), xếp loại HEALTHY/MODERATE/AT_RISK/CRITICAL.
    """
    return repo_health_model.evaluate(request.model_dump())


@router.post("/language-health")
async def calculate_language_health(request: LanguageHealthRequest) -> Dict[str, Any]:
    """
    Tính toán chỉ số Language Health (0-100) cho ngôn ngữ lập trình.
    """
    return lang_health_model.evaluate(request.model_dump())


@router.post("/trend-analysis")
async def analyze_technology_trend(request: TrendAnalysisRequest) -> Dict[str, Any]:
    """
    Phân tích xu hướng phát triển công nghệ (EMERGING, GROWING, STABLE, DECLINING).
    """
    return trend_analyzer.analyze(request.technology, request.series_values)


from app.core.crawl_config import CrawlConfigManager


class CrawlConfigUpdateRequest(BaseModel):
    crawl_interval_minutes: Optional[float] = None
    max_repos_per_job: Optional[int] = None
    min_stars: Optional[int] = None
    max_stars: Optional[int] = None
    random_page_max: Optional[int] = None
    queries: Optional[List[str]] = None
    sort_options: Optional[List[str]] = None


@router.get("/crawl-config")
async def get_crawl_config() -> Dict[str, Any]:
    """
    Xem cấu hình và mockdata các chỉ tiêu cào dữ liệu hiện tại (từ crawl_config.json).
    """
    return CrawlConfigManager.load_config()


@router.post("/crawl-config")
async def update_crawl_config(request: CrawlConfigUpdateRequest) -> Dict[str, Any]:
    """
    Cập nhật các chỉ tiêu cào dữ liệu mới (gửi payload JSON dạng mockdata để cấu hình).
    """
    update_data = {k: v for k, v in request.model_dump().items() if v is not None}
    success = CrawlConfigManager.save_config(update_data)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update crawl_config.json")
    return {
        "status": "success",
        "message": "Crawl configuration updated successfully.",
        "config": CrawlConfigManager.load_config()
    }


from fastapi import BackgroundTasks
from app.jobs.scheduler import scheduled_daily_train_job
from app.core_models.data.db_loader import DatabaseDataLoader


@router.post("/retrain-now")
async def trigger_retrain_now(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """
    Kích hoạt tiến trình cào dữ liệu mới nhất & huấn luyện lại (Retrain) các Core ML Models ngay lập tức.
    """
    background_tasks.add_task(scheduled_daily_train_job)
    return {
        "status": "success",
        "message": "Daily Model Retraining & Data Sync job triggered in background."
    }


@router.get("/repository-health/history")
async def get_repository_health_history(
    full_name: str = Query(..., description="Tên repository (vd: facebook/react)"),
    limit: int = Query(30, ge=1, le=100)
) -> List[Dict[str, Any]]:
    """
    Lấy chuỗi lịch sử điểm sức khỏe của một Repository phục vụ vẽ biểu đồ (Chart).
    """
    return await DatabaseDataLoader.get_repository_health_history(repo_name=full_name, limit=limit)


@router.get("/language-health/history")
async def get_language_health_history(
    language: str = Query(..., description="Tên ngôn ngữ lập trình (vd: Python)"),
    limit: int = Query(30, ge=1, le=100)
) -> List[Dict[str, Any]]:
    """
    Lấy chuỗi lịch sử điểm sức khỏe & xu hướng Ngôn ngữ lập trình phục vụ vẽ biểu đồ (Chart).
    """
    return await DatabaseDataLoader.get_language_health_history(language=language, limit=limit)


@router.get("/model-performance/logs")
async def get_model_performance_logs(
    limit: int = Query(10, ge=1, le=50)
) -> List[Dict[str, Any]]:
    """
    Lấy danh sách nhật ký đánh giá hiệu năng (MAE, RMSE, MAPE) & cảnh báo sụt giảm mô hình.
    """
    return await DatabaseDataLoader.get_latest_model_performance_logs(limit=limit)

