import pytest
import uuid
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport, Response
from app.main import app
from app.core.token_manager import TokenManager, TokenStatus, TokenEntry
from app.core.github_client import GithubClient


@pytest.mark.asyncio
async def test_token_manager_rotation_and_rate_limit():
    manager = TokenManager()
    entry1 = TokenEntry(token="ghp_test_token_111111111111", description="Token 1")
    entry2 = TokenEntry(token="ghp_test_token_222222222222", description="Token 2")
    manager.tokens = [entry1, entry2]
    manager._initialized = True

    # 1. Ban đầu token 1 active
    active = await manager.get_active_token()
    assert active is not None
    assert active.token == "ghp_test_token_111111111111"
    assert active.status == TokenStatus.ACTIVE

    # 2. Đánh dấu token 1 bị RATE_LIMITED
    next_token = await manager.mark_rate_limited("ghp_test_token_111111111111")
    assert entry1.status == TokenStatus.RATE_LIMITED
    assert next_token is not None
    assert next_token.token == "ghp_test_token_222222222222"

    # 3. Lần get_active_token tiếp theo phải trả về token 2 (đã swap)
    active2 = await manager.get_active_token()
    assert active2 is not None
    assert active2.token == "ghp_test_token_222222222222"
    assert active2.status == TokenStatus.ACTIVE

    # 4. Khi token 2 cũng bị RATE_LIMITED, pool cạn kiệt trả về None
    await manager.mark_rate_limited("ghp_test_token_222222222222")
    assert entry2.status == TokenStatus.RATE_LIMITED
    active_none = await manager.get_active_token()
    assert active_none is None


@pytest.mark.asyncio
async def test_token_manager_admin_crud():
    manager = TokenManager()
    manager.tokens = []
    manager._initialized = True

    # Mock call verify online
    mock_verify_client = MagicMock()
    mock_verify_client.__aenter__.return_value.get.return_value = MagicMock(
        status_code=200,
        json=lambda: {"resources": {"core": {"remaining": 4900, "limit": 5000, "reset": 1800000000}}}
    )
    with patch("app.core.token_manager.httpx.AsyncClient", return_value=mock_verify_client):
        created = await manager.add_token("ghp_sample_new_token_123456", "Test Admin Token")
        assert created["token_preview"].startswith("ghp_samp")
        assert created["status"] == TokenStatus.ACTIVE
        token_id = created["token_id"]

        # List
        tokens = await manager.list_tokens()
        assert len(tokens) == 1
        assert tokens[0]["token"] == "********"

        # Toggle Disabled
        updated = await manager.toggle_token(token_id, is_active=False)
        assert updated["status"] == TokenStatus.DISABLED

        # Toggle Active
        updated_active = await manager.toggle_token(token_id, is_active=True)
        assert updated_active["status"] == TokenStatus.ACTIVE

        # Remove
        removed = await manager.remove_token(token_id)
        assert removed is True
        assert len(await manager.list_tokens()) == 0


@pytest.mark.asyncio
async def test_github_client_auto_swap_on_403():
    """Kiểm thử khi request 1 gặp 403, GithubClient tự động swap sang token 2 và retry thành công."""
    from app.core.token_manager import token_manager

    entry1 = TokenEntry(token="ghp_token_blocked_00000001", description="Token Blocked")
    entry2 = TokenEntry(token="ghp_token_working_00000002", description="Token Working")
    token_manager.tokens = [entry1, entry2]
    token_manager._initialized = True
    token_manager.current_index = 0

    client_instance = GithubClient()

    # Lần 1: trả về 403 Rate Limit với header reset
    mock_resp_403 = MagicMock()
    mock_resp_403.status_code = 403
    mock_resp_403.headers = {"x-ratelimit-remaining": "0", "x-ratelimit-limit": "5000", "x-ratelimit-reset": "1800000000"}

    # Lần 2: sau khi swap sang token 2, trả về 200 OK
    mock_resp_200 = MagicMock()
    mock_resp_200.status_code = 200
    mock_resp_200.headers = {"x-ratelimit-remaining": "4950", "x-ratelimit-limit": "5000"}
    mock_resp_200.json.return_value = {"id": 12345, "name": "swapped-repo"}
    mock_resp_200.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.side_effect = [mock_resp_403, mock_resp_200]

    result = await client_instance._get(mock_client, "https://api.github.com/repos/test/repo")

    assert result == {"id": 12345, "name": "swapped-repo"}
    # Token 1 phải bị chuyển sang RATE_LIMITED
    assert entry1.status == TokenStatus.RATE_LIMITED
    # Token 2 được dùng và active
    assert entry2.status == TokenStatus.ACTIVE


@pytest.mark.asyncio
async def test_admin_token_api_endpoints():
    from app.core.token_manager import token_manager

    token_manager.tokens = []
    token_manager._initialized = True

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. GET tokens ban đầu rỗng
        res = await client.get("/api/v1/crawl/tokens")
        assert res.status_code == 200
        assert res.json()["total"] == 0

        # 2. POST thêm token mới (mock verify online trong token_manager)
        mock_verify_client = MagicMock()
        mock_verify_client.__aenter__.return_value.get.return_value = MagicMock(
            status_code=200,
            json=lambda: {"resources": {"core": {"remaining": 4990, "limit": 5000}}}
        )
        with patch("app.core.token_manager.httpx.AsyncClient", return_value=mock_verify_client):
            res_add = await client.post("/api/v1/crawl/tokens", json={
                "token": "ghp_mock_admin_token_9876543210",
                "description": "Admin Added Token"
            })
            assert res_add.status_code == 201
            data = res_add.json()["token"]
            token_id = data["token_id"]
            assert data["description"] == "Admin Added Token"

        # 3. GET lại danh sách
        res_list = await client.get("/api/v1/crawl/tokens")
        assert res_list.status_code == 200
        assert res_list.json()["total"] == 1

        # 4. PATCH toggle
        res_toggle = await client.patch(f"/api/v1/crawl/tokens/{token_id}/toggle", json={"is_active": False})
        assert res_toggle.status_code == 200
        assert res_toggle.json()["token"]["status"] == "DISABLED"

        # 5. DELETE token
        res_del = await client.delete(f"/api/v1/crawl/tokens/{token_id}")
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "success"
