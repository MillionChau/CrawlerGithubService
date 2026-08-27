import httpx
import asyncio
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class GithubClient:
    def __init__(self):
        self.base_url = settings.GITHUB_API_URL

    def get_headers(self, raw_content: bool = False) -> dict:
        headers = {
            "Accept": "application/vnd.github.v3.raw" if raw_content else "application/vnd.github.v3+json",
            "User-Agent": "DevRadar-Crawler"
        }
        token = settings.GITHUB_ACCESS_TOKEN
        if token and token.strip():
            token_str = token.strip()
            if token_str.startswith("github_pat_"):
                headers["Authorization"] = f"Bearer {token_str}"
            else:
                headers["Authorization"] = f"token {token_str}"
        return headers

    async def _get(self, client, url, params=None):
        try:
            response = await client.get(url, params=params)
            if response.status_code in (403, 429):
                logger.warning(f"GitHub API Rate Limit hit for {url}. Skipping sub-request to avoid blocking.")
                return None
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    async def fetch_repositories(self, query: str = "stars:>1000", max_pages: int = 1, page: int = 1, sort: str = "stars"):
        all_repos = []
        headers = self.get_headers()
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            for p in range(page, page + max_pages):
                url = f"{self.base_url}/search/repositories"
                params = {"q": query, "sort": sort, "order": "desc", "per_page": 10, "page": p}
                data = await self._get(client, url, params)
                if data and "items" in data:
                    all_repos.extend(data["items"])
                await asyncio.sleep(1)
        return all_repos

    async def fetch_user(self, username: str):
        url = f"{self.base_url}/users/{username}"
        headers = self.get_headers()
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            return await self._get(client, url)

    async def fetch_repo_commits(self, owner: str, repo: str, per_page: int = 10):
        url = f"{self.base_url}/repos/{owner}/{repo}/commits"
        params = {"per_page": per_page}
        headers = self.get_headers()
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            return await self._get(client, url, params) or []

    async def fetch_repo_pulls(self, owner: str, repo: str, per_page: int = 10):
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        params = {"state": "all", "per_page": per_page}
        headers = self.get_headers()
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            return await self._get(client, url, params) or []

    async def fetch_repo_issues(self, owner: str, repo: str, per_page: int = 10):
        url = f"{self.base_url}/repos/{owner}/{repo}/issues"
        params = {"state": "all", "per_page": per_page}
        headers = self.get_headers()
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            return await self._get(client, url, params) or []

    async def fetch_repo_file_content(self, owner: str, repo: str, file_path: str):
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{file_path}"
        headers = self.get_headers(raw_content=True)
        async with httpx.AsyncClient(headers=headers, timeout=30.0) as client:
            try:
                response = await client.get(url)
                if response.status_code == 200:
                    return response.text
                return None
            except Exception:
                return None


github_client = GithubClient()
