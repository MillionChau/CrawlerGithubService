import pytest
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.mongo import mongo_client
from app.db.models import CrawlLogModel
from app.services.pipelines.crawler_pipeline import CrawlerPipeline


@pytest.mark.asyncio
async def test_mongo_crawl_log_crud():
    session_id = f"test-{uuid.uuid4()}"
    log_data = {
        "session_id": session_id,
        "started_at": datetime.utcnow(),
        "finished_at": None,
        "duration_seconds": None,
        "trigger_type": "MANUAL",
        "query": "stars:>5000",
        "status": "RUNNING",
        "repos_crawled": 0,
        "new_repos_count": 0,
        "updated_repos_count": 0,
        "crawled_repo_names": [],
        "github_rate_limit_remaining": None,
        "error_message": None
    }

    # 1. Test create_crawl_log
    created_id = await mongo_client.create_crawl_log(log_data)
    assert created_id == session_id

    # 2. Test get_crawl_log_by_id
    retrieved = await mongo_client.get_crawl_log_by_id(session_id)
    assert retrieved is not None
    assert retrieved["session_id"] == session_id
    assert retrieved["status"] == "RUNNING"

    # 3. Test update_crawl_log
    updated = await mongo_client.update_crawl_log(session_id, {
        "status": "SUCCESS",
        "repos_crawled": 3,
        "new_repos_count": 2,
        "updated_repos_count": 1,
        "crawled_repo_names": ["user/repo1", "user/repo2", "user/repo3"],
        "duration_seconds": 4.5
    })
    assert updated is True

    # 4. Verify updated log
    after_update = await mongo_client.get_crawl_log_by_id(session_id)
    assert after_update["status"] == "SUCCESS"
    assert after_update["repos_crawled"] == 3
    assert len(after_update["crawled_repo_names"]) == 3

    # 5. Test get_crawl_logs list & filter
    total, items = await mongo_client.get_crawl_logs(page=1, limit=10, status="SUCCESS")
    assert total >= 1
    assert any(item["session_id"] == session_id for item in items)


@pytest.mark.asyncio
async def test_api_crawl_history_endpoints():
    session_id = f"api-test-{uuid.uuid4()}"
    log_entry = {
        "session_id": session_id,
        "started_at": datetime.utcnow().isoformat(),
        "finished_at": datetime.utcnow().isoformat(),
        "duration_seconds": 5.2,
        "trigger_type": "SCHEDULED",
        "query": "stars:>1000",
        "status": "SUCCESS",
        "repos_crawled": 2,
        "new_repos_count": 1,
        "updated_repos_count": 1,
        "crawled_repo_names": ["test/repo-a", "test/repo-b"],
        "github_rate_limit_remaining": 4900,
        "error_message": None
    }
    await mongo_client.create_crawl_log(log_entry)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # UC-76: List history
        res_list = await client.get("/api/v1/crawl/history?page=1&limit=20")
        assert res_list.status_code == 200
        data_list = res_list.json()
        assert "total" in data_list
        assert "items" in data_list
        assert data_list["page"] == 1
        assert any(item["session_id"] == session_id for item in data_list["items"])

        # UC-77: Detail existing
        res_detail = await client.get(f"/api/v1/crawl/history/{session_id}")
        assert res_detail.status_code == 200
        detail_data = res_detail.json()
        assert detail_data["session_id"] == session_id
        assert detail_data["repos_crawled"] == 2
        assert "test/repo-a" in detail_data["crawled_repo_names"]

        # UC-77: Detail non-existent -> 404
        res_404 = await client.get("/api/v1/crawl/history/non-existent-session-id")
        assert res_404.status_code == 404


@pytest.mark.asyncio
async def test_crawler_pipeline_records_log():
    pipeline = CrawlerPipeline()
    mock_raw_repos = [
        {
            "id": 999991,
            "name": "test-crawl-repo",
            "full_name": "mockowner/test-crawl-repo",
            "owner": {"login": "mockowner"},
            "stargazers_count": 500,
            "forks_count": 50,
            "open_issues_count": 2,
            "created_at": "2024-01-01T00:00:00Z",
            "updated_at": "2024-06-01T00:00:00Z"
        }
    ]

    with patch("app.core.github_client.github_client.fetch_repositories_graphql", new=AsyncMock(return_value=None)), \
         patch("app.core.github_client.github_client.fetch_repositories", new=AsyncMock(return_value=mock_raw_repos)), \
         patch("app.core.github_client.github_client.fetch_user", new=AsyncMock(return_value={"login": "mockowner"})), \
         patch("app.core.github_client.github_client.fetch_repo_commits", new=AsyncMock(return_value=[])), \
         patch("app.core.github_client.github_client.fetch_repo_pulls", new=AsyncMock(return_value=[])), \
         patch("app.core.github_client.github_client.fetch_repo_file_content", new=AsyncMock(return_value=None)), \
         patch("app.core.github_client.github_client.fetch_rate_limit", new=AsyncMock(return_value=4950)):

        custom_session = f"custom-{uuid.uuid4()}"
        results = await pipeline.execute(
            query="stars:>5000",
            max_repos=1,
            trigger_type="MANUAL",
            session_id=custom_session
        )

        assert len(results) == 1
        log = await mongo_client.get_crawl_log_by_id(custom_session)
        assert log is not None
        assert log["session_id"] == custom_session
        assert log["status"] == "SUCCESS"
        assert log["repos_crawled"] == 1
        assert "mockowner/test-crawl-repo" in log["crawled_repo_names"]
        assert log["github_rate_limit_remaining"] == 4950
