import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.main import app
from app.clients.ai_client import AIClient, AIKeyStatus
from app.services.report_generator import TechReportGenerator


@pytest.fixture
def client():
    return TestClient(app)


def test_ai_key_status_cooldown():
    status = AIKeyStatus("sk-test1234567890abcdef")
    assert status.masked.startswith("sk-tes")
    assert not status.is_cooling()

    # Mark cooling
    status.mark_cooling(seconds=10)
    assert status.is_cooling()
    assert status.rate_limited_count == 1

    # Mark success
    status.mark_success()
    assert status.total_calls == 1
    assert status.success_calls == 1


@pytest.mark.asyncio
async def test_ai_client_key_swapping_on_429():
    client = AIClient()
    client.keys = [
        AIKeyStatus("key-1"),
        AIKeyStatus("key-2")
    ]
    client.enabled = True

    mock_resp_429 = MagicMock()
    mock_resp_429.status_code = 429
    mock_resp_429.text = "Rate limit exceeded"

    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.json.return_value = {
        "choices": [{"message": {"content": "Hello from key-2!"}}]
    }

    with patch("httpx.AsyncClient.post", side_effect=[mock_resp_429, mock_resp_200]):
        result = await client.chat_completion([{"role": "user", "content": "Hi"}])
        assert result == "Hello from key-2!"
        assert client.keys[0].is_cooling()
        assert client.keys[1].success_calls == 1


@pytest.mark.asyncio
async def test_report_generator_heuristic_fallback():
    mock_repos = [
        {
            "name": "cpython",
            "full_name": "python/cpython",
            "primary_language": "Python",
            "stars": 60000,
            "forks": 30000,
            "description": "The Python programming language"
        }
    ]
    with patch("app.core_models.data.db_loader.DatabaseDataLoader.get_all_repositories", new_callable=AsyncMock, return_value=mock_repos), \
         patch("app.clients.ai_client.ai_client.is_available", return_value=False):
        report = await TechReportGenerator.generate_report(
            topic="Báo cáo thử nghiệm Heuristic Fallback",
            category="LANGUAGE",
            target_tech="Python"
        )
        assert report is not None
        assert report["title"] == "Báo cáo thử nghiệm Heuristic Fallback"
        assert report["category"] == "LANGUAGE"
        assert "content_markdown" in report
        assert "# Báo cáo thử nghiệm Heuristic Fallback" in report["content_markdown"]
        assert "tags" in report
        assert "metrics_snapshot" in report
        assert report["ai_generated"] is False


def test_api_ai_status(client):
    res = client.get("/api/v1/admin/ai/status")
    assert res.status_code == 200
    data = res.json()
    assert "total_keys" in data
    assert "active_keys_count" in data
    assert "model" in data


def test_api_ai_report_suggestions(client):
    mock_overview = {
        "total_repositories": 1200,
        "top_languages": [
            {"language": "Python", "repo_count": 350},
            {"language": "Rust", "repo_count": 220},
            {"language": "Go", "repo_count": 180}
        ]
    }
    with patch("app.db.mongo.mongo_client.get_system_overview", new_callable=AsyncMock, return_value=mock_overview):
        res = client.get("/api/v1/admin/reports/ai-suggestions")
        assert res.status_code == 200
        data = res.json()
        assert "suggested_topics" in data
        assert len(data["suggested_topics"]) > 0


def test_api_ai_generate_report_endpoint(client):
    mock_generated = {
        "title": "Phân tích xu hướng phát triển hệ sinh thái Go và Microservices 2026",
        "summary": "Tóm tắt phân tích Go 2026",
        "content_markdown": "# Phân tích Go 2026\n\nNội dung chi tiết...",
        "category": "TREND",
        "tags": ["go", "microservices"],
        "metrics_snapshot": {"total_stars": 50000},
        "slug": "phan-tich-go-2026-abc123",
        "ai_generated": True,
        "model_used": "qwen2.5-coder-32b:free"
    }

    with patch("app.services.report_generator.report_generator.generate_report", new_callable=AsyncMock, return_value=mock_generated), \
         patch("app.db.mongo.mongo_client.create_tech_report", new_callable=AsyncMock, return_value="mock-id"):
        payload = {
            "topic": "Phân tích xu hướng phát triển hệ sinh thái Go và Microservices 2026",
            "category": "TREND",
            "target_tech": "Go",
            "save_to_db": True,
            "status": "DRAFT",
            "include_live_metrics": True
        }
        res = client.post("/api/v1/admin/reports/ai-generate", json=payload)
        assert res.status_code == 201
        data = res.json()
        assert data["status"] == "success"
        assert data["ai_generated"] is True
        assert "data" in data
        report_data = data["data"]
        assert report_data["category"] == "TREND"
        assert "slug" in report_data
        assert report_data["status"] == "DRAFT"


from app.core.crawl_config import CrawlConfigManager
from app.jobs.scheduler import scheduled_auto_generate_reports_job


def test_crawl_config_auto_report_settings():
    assert isinstance(CrawlConfigManager.is_auto_report_enabled(), bool)
    assert CrawlConfigManager.get_auto_report_interval_hours() > 0
    assert CrawlConfigManager.get_auto_report_status() in ["DRAFT", "PUBLISHED"]
    assert isinstance(CrawlConfigManager.get_auto_report_categories(), list)
    assert len(CrawlConfigManager.get_auto_report_categories()) > 0
    assert CrawlConfigManager.get_auto_report_max_per_run() >= 1


@pytest.mark.asyncio
async def test_scheduled_auto_generate_reports_job_execution():
    mock_overview = {
        "total_repositories": 1500,
        "top_languages": [
            {"language": "TypeScript", "repo_count": 400},
            {"language": "Python", "repo_count": 350}
        ]
    }
    mock_generated = {
        "title": "Báo cáo toàn cảnh TypeScript 2026",
        "summary": "Tóm tắt TypeScript 2026",
        "content_markdown": "# TypeScript 2026\n\nNội dung phân tích...",
        "category": "LANGUAGE",
        "tags": ["typescript", "trend-2026"],
        "metrics_snapshot": {"total_stars": 80000},
        "slug": "typescript-2026-xyz789",
        "ai_generated": True,
        "model_used": "qwen2.5-coder-32b:free"
    }

    with patch("app.core.crawl_config.CrawlConfigManager.is_auto_report_enabled", return_value=True), \
         patch("app.db.mongo.mongo_client.get_system_overview", new_callable=AsyncMock, return_value=mock_overview), \
         patch("app.db.mongo.mongo_client.get_tech_reports", new_callable=AsyncMock, return_value=(0, [])), \
         patch("app.services.report_generator.report_generator.generate_report", new_callable=AsyncMock, return_value=mock_generated), \
         patch("app.db.mongo.mongo_client.create_tech_report", new_callable=AsyncMock, return_value="auto-report-id"):
        
        result = await scheduled_auto_generate_reports_job()
        assert result is not None
        assert result["title"] == "Báo cáo toàn cảnh TypeScript 2026"
        assert result["author_id"] == "ai-scheduler"
        assert result["status"] == CrawlConfigManager.get_auto_report_status()


@pytest.mark.asyncio
async def test_scheduled_auto_generate_reports_job_disabled():
    with patch("app.core.crawl_config.CrawlConfigManager.is_auto_report_enabled", return_value=False):
        result = await scheduled_auto_generate_reports_job()
        assert result is None


def test_api_scheduler_trigger_report_now(client):
    with patch("app.main.scheduled_auto_generate_reports_job", new_callable=AsyncMock):
        res = client.post("/scheduler/trigger-report-now")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "success"
        assert "triggered in background" in data["message"]


