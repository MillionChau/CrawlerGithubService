import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.core.crawl_config import CrawlConfigManager
from app.services.data_cleaner import DataCleaner
from app.services.pipelines.repo_updater_pipeline import RepoUpdaterPipeline


def test_crawl_config_update_settings():
    interval = CrawlConfigManager.get_update_interval_minutes()
    batch_size = CrawlConfigManager.get_update_batch_size()

    assert isinstance(interval, (int, float))
    assert interval > 0
    assert isinstance(batch_size, int)
    assert batch_size > 0


def test_data_cleaner_has_last_synced_at():
    raw_repo = {
        "id": 12345,
        "name": "test-repo",
        "full_name": "owner/test-repo",
        "description": "A sample repo",
        "language": "Python",
        "stargazers_count": 150,
        "forks_count": 25,
        "open_issues_count": 3,
        "visibility": "public",
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-06-01T00:00:00Z"
    }
    owner_data = {"username": "owner"}
    frameworks = ["FastAPI"]
    metrics = {"commits": [], "pulls": []}

    cleaned = DataCleaner.process_repo(raw_repo, owner_data, frameworks, metrics)
    assert cleaned["id"] == "12345"
    assert cleaned["full_name"] == "owner/test-repo"
    assert "last_synced_at" in cleaned
    assert len(cleaned["last_synced_at"]) > 0


@pytest.mark.asyncio
async def test_repo_updater_pipeline_candidates():
    pipeline = RepoUpdaterPipeline()
    candidates = await pipeline.get_candidate_repositories(limit=3)
    assert isinstance(candidates, list)


@pytest.mark.asyncio
async def test_repo_updater_pipeline_execute_mock():
    pipeline = RepoUpdaterPipeline()
    
    mock_candidates = [
        {
            "id": "111",
            "name": "repo1",
            "full_name": "user1/repo1",
            "owner": {"username": "user1"}
        }
    ]
    
    with patch.object(pipeline, 'get_candidate_repositories', new=AsyncMock(return_value=mock_candidates)), \
         patch.object(pipeline, 'update_single_repository', new=AsyncMock(return_value={"id": "111", "full_name": "user1/repo1"})):
        summary = await pipeline.execute(batch_size=1)
        assert summary["status"] == "success"
        assert summary["total_candidates"] == 1
        assert summary["updated_count"] == 1
        assert "user1/repo1" in summary["updated_repos"]
