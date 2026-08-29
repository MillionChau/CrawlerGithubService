import pytest
import os
import pandas as pd
from app.core_models.health.repository_health import RepositoryHealthModel
from app.core_models.health.language_health import LanguageHealthModel
from app.core_models.trend.trend_analyzer import TechnologyTrendAnalyzer
from app.core_models.forecasting.forecasting_service import ForecastingService
from app.core_models.evaluation.metrics import ModelEvaluator
from app.core_models.persistence.model_manager import ModelManager


def test_repository_health_model():
    model = RepositoryHealthModel()
    repo_data = {
        "full_name": "facebook/react",
        "stars": 220000,
        "forks": 45000,
        "open_issues": 500,
        "closed_issues_30d": 120,
        "contributors_count": 1500,
        "recent_commits_30d": 80,
        "days_since_last_push": 1,
        "star_growth_rate_30d": 0.08
    }
    result = model.evaluate(repo_data)

    assert result["repository"] == "facebook/react"
    assert 0 <= result["health_score"] <= 100
    assert result["health_level"] in ["HEALTHY", "MODERATE", "AT_RISK", "CRITICAL"]
    assert "activity_score" in result["components"]
    assert "community_score" in result["components"]
    assert "maintenance_score" in result["components"]
    assert "growth_score" in result["components"]


def test_language_health_model():
    model = LanguageHealthModel()
    lang_data = {
        "language": "Python",
        "repository_count": 50000,
        "total_stars": 3000000,
        "total_forks": 800000,
        "commit_activity_index": 85.0,
        "contributor_activity_index": 90.0,
        "repo_growth_rate": 0.06,
        "star_growth_rate": 0.10
    }
    result = model.evaluate(lang_data)

    assert result["language"] == "Python"
    assert 0 <= result["health_score"] <= 100
    assert result["health_level"] in ["HEALTHY", "MODERATE", "AT_RISK", "CRITICAL"]
    assert "repo_density_score" in result["metrics"]


def test_trend_analyzer():
    analyzer = TechnologyTrendAnalyzer()
    series_data = [100.0, 120.0, 145.0, 180.0, 230.0]
    result = analyzer.analyze("Rust", series_data)

    assert result["technology"] == "Rust"
    assert result["trend"] in ["EMERGING", "GROWING", "STABLE", "DECLINING"]
    assert "growth_rate" in result
    assert "momentum" in result


def test_forecasting_service():
    service = ForecastingService()
    history = [
        {"timestamp": "2025-01-01", "value": 100.0},
        {"timestamp": "2025-02-01", "value": 110.0},
        {"timestamp": "2025-03-01", "value": 125.0},
        {"timestamp": "2025-04-01", "value": 140.0},
        {"timestamp": "2025-05-01", "value": 160.0}
    ]
    result = service.predict_technology("TypeScript", history, steps=3)

    assert result["technology"] == "TypeScript"
    assert len(result["forecast"]) == 3
    for point in result["forecast"]:
        assert "timestamp" in point
        assert "predicted_value" in point
        assert "lower_bound" in point
        assert "upper_bound" in point


def test_model_evaluator():
    y_true = [10.0, 20.0, 30.0]
    y_pred = [11.0, 19.0, 31.0]
    metrics = ModelEvaluator.evaluate_forecasting(y_true, y_pred)

    assert "mae" in metrics
    assert "rmse" in metrics
    assert "mape" in metrics


def test_performance_tracker():
    from app.core_models.evaluation.metrics import PerformanceTracker

    prev_metrics = {"mae": 1.0, "rmse": 2.0, "mape": 5.0}
    
    # Healthy case
    curr_metrics_good = {"mae": 1.05, "rmse": 2.10, "mape": 5.25}
    res_good = PerformanceTracker.detect_degradation(curr_metrics_good, prev_metrics, threshold_percentage=20.0)
    assert res_good["degraded"] is False
    assert res_good["status"] == "HEALTHY"

    # Degraded case (RMSE increased by > 20%)
    curr_metrics_bad = {"mae": 2.50, "rmse": 3.50, "mape": 15.0}
    res_bad = PerformanceTracker.detect_degradation(curr_metrics_bad, prev_metrics, threshold_percentage=20.0)
    assert res_bad["degraded"] is True
    assert res_bad["status"] == "DEGRADED"
    assert "WARNING" in res_bad["message"]


def test_model_manager(tmp_path):
    manager = ModelManager(base_dir=str(tmp_path))
    sample_artifact = {"weights": {"activity": 0.3}, "version": "1.0"}
    
    saved_path = manager.save_model(sample_artifact, "repository_health", "test_health_model")
    assert os.path.exists(saved_path)

    loaded_artifact = manager.load_model("repository_health", "test_health_model")
    assert loaded_artifact is not None
    assert loaded_artifact["version"] == "1.0"

