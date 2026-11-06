import httpx
import asyncio
import logging
from app.core.config import settings
from app.core.token_manager import token_manager

logger = logging.getLogger(__name__)


class GithubClient:
    def __init__(self):
        self.base_url = settings.GITHUB_API_URL

    def _create_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, follow_redirects=True)

    def get_headers(self, token_str: str | None = None, raw_content: bool = False) -> dict:
        headers = {
            "Accept": "application/vnd.github.v3.raw" if raw_content else "application/vnd.github.v3+json",
            "User-Agent": "DevRadar-Crawler"
        }
        if token_str and token_str.strip():
            clean = token_str.strip()
            if clean.startswith("github_pat_"):
                headers["Authorization"] = f"Bearer {clean}"
            else:
                headers["Authorization"] = f"token {clean}"
        elif settings.GITHUB_ACCESS_TOKEN and settings.GITHUB_ACCESS_TOKEN.strip():
            clean = settings.GITHUB_ACCESS_TOKEN.strip()
            if clean.startswith("github_pat_"):
                headers["Authorization"] = f"Bearer {clean}"
            else:
                headers["Authorization"] = f"token {clean}"
        return headers

    async def _get(self, client: httpx.AsyncClient, url: str, params: dict = None, raw_content: bool = False):
        """
        Gửi HTTP GET tới GitHub API kèm cơ chế tự động hoán đổi (Swap) token khi gặp 403 Rate Limit hoặc 429.
        """
        max_attempts = max(2, len(token_manager.tokens) + 1)

        for attempt in range(max_attempts):
            token_entry = await token_manager.get_active_token()
            token_val = token_entry.token if token_entry else settings.GITHUB_ACCESS_TOKEN
            headers = self.get_headers(token_str=token_val, raw_content=raw_content)

            try:
                response = await client.get(url, params=params, headers=headers)

                # Cập nhật số liệu quota nếu có header
                remaining = response.headers.get("x-ratelimit-remaining")
                limit = response.headers.get("x-ratelimit-limit")
                reset_ts = response.headers.get("x-ratelimit-reset")

                if token_entry and remaining is not None:
                    try:
                        await token_manager.update_quota(
                            token_entry.token,
                            int(remaining),
                            int(limit or 5000),
                            int(reset_ts) if reset_ts else None
                        )
                    except Exception:
                        pass

                # Xử lý khi bị Rate Limit (403, 429)
                if response.status_code in (403, 429):
                    preview = token_entry.token_preview if token_entry else "anonymous"
                    logger.warning(f"⚠️ GitHub API Rate Limit hit for {url} using token {preview}.")
                    if token_entry:
                        await token_manager.mark_rate_limited(token_entry.token, int(reset_ts) if reset_ts else None)
                        logger.info(f"🔄 Swapping token! Retrying request with next token in pool (attempt {attempt + 1}/{max_attempts})...")
                        await asyncio.sleep(0.5)
                        continue
                    else:
                        logger.warning("No more tokens in pool. Skipping sub-request to avoid blocking.")
                        return None

                # Xử lý khi token bị 401 Unauthorized / Hết hạn
                elif response.status_code == 401:
                    preview = token_entry.token_preview if token_entry else "anonymous"
                    logger.error(f"❌ GitHub Token {preview} is expired/unauthorized (401).")
                    if token_entry:
                        await token_manager.mark_expired(token_entry.token)
                        continue
                    return None

                # Xử lý khi repository/resource không tồn tại hoặc bị đổi thành private (404)
                elif response.status_code == 404:
                    logger.info(f"ℹ️ GitHub repository or resource not found (404): {url}")
                    return None

                response.raise_for_status()
                return response.text if raw_content else response.json()
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error fetching {url}: {e}")
                return None
            except Exception as e:
                logger.error(f"Error fetching {url}: {e}")
                return None

        return None

    async def fetch_repositories(self, query: str = "stars:>1000", max_pages: int = 1, page: int = 1, sort: str = "stars"):
        all_repos = []
        async with self._create_client(timeout=30.0) as client:
            for p in range(page, page + max_pages):
                url = f"{self.base_url}/search/repositories"
                params = {"q": query, "sort": sort, "order": "desc", "per_page": 10, "page": p}
                data = await self._get(client, url, params)
                if data and "items" in data:
                    all_repos.extend(data["items"])
                await asyncio.sleep(0.5)
        return all_repos

    async def fetch_repository(self, owner: str, repo: str):
        url = f"{self.base_url}/repos/{owner}/{repo}"
        async with self._create_client(timeout=30.0) as client:
            return await self._get(client, url)

    async def fetch_user(self, username: str):
        url = f"{self.base_url}/users/{username}"
        async with self._create_client(timeout=30.0) as client:
            return await self._get(client, url)

    async def fetch_repo_commits(self, owner: str, repo: str, per_page: int = 10):
        url = f"{self.base_url}/repos/{owner}/{repo}/commits"
        params = {"per_page": per_page}
        async with self._create_client(timeout=30.0) as client:
            return await self._get(client, url, params) or []

    async def fetch_repo_pulls(self, owner: str, repo: str, per_page: int = 10):
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls"
        params = {"state": "all", "per_page": per_page}
        async with self._create_client(timeout=30.0) as client:
            return await self._get(client, url, params) or []

    async def fetch_repo_issues(self, owner: str, repo: str, per_page: int = 10):
        url = f"{self.base_url}/repos/{owner}/{repo}/issues"
        params = {"state": "all", "per_page": per_page}
        async with self._create_client(timeout=30.0) as client:
            return await self._get(client, url, params) or []

    async def fetch_repo_file_content(self, owner: str, repo: str, file_path: str):
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{file_path}"
        async with self._create_client(timeout=30.0) as client:
            return await self._get(client, url, raw_content=True)

    async def fetch_graphql(self, query: str, variables: dict = None):
        """
        Thực thi GraphQL Query với GitHub GraphQL API v4 (https://api.github.com/graphql).
        Tự động hoán đổi token (Swap) và retry nếu gặp 403 Rate Limit hoặc 401 Unauthorized.
        """
        graphql_url = "https://api.github.com/graphql"
        payload = {"query": query, "variables": variables or {}}
        max_attempts = max(2, len(token_manager.tokens) + 1)

        for attempt in range(max_attempts):
            token_entry = await token_manager.get_active_token()
            token_val = token_entry.token if token_entry else settings.GITHUB_ACCESS_TOKEN

            if not token_val:
                logger.warning("No token available for GraphQL API. Skipping GraphQL and fallback to REST.")
                return None

            headers = self.get_headers(token_str=token_val)
            headers["Content-Type"] = "application/json"

            async with self._create_client(timeout=30.0) as client:
                try:
                    response = await client.post(graphql_url, json=payload, headers=headers)

                    # Đọc và cập nhật quota GraphQL
                    remaining = response.headers.get("x-ratelimit-remaining")
                    limit = response.headers.get("x-ratelimit-limit")
                    reset_ts = response.headers.get("x-ratelimit-reset")

                    if token_entry and remaining is not None:
                        try:
                            await token_manager.update_quota(
                                token_entry.token,
                                int(remaining),
                                int(limit or 5000),
                                int(reset_ts) if reset_ts else None
                            )
                        except Exception:
                            pass

                    if response.status_code in (403, 429):
                        preview = token_entry.token_preview if token_entry else "anonymous"
                        logger.warning(f"⚠️ GitHub GraphQL Rate Limit hit for token {preview}.")
                        if token_entry:
                            await token_manager.mark_rate_limited(token_entry.token, int(reset_ts) if reset_ts else None)
                            logger.info(f"🔄 Swapping GraphQL token! Retrying (attempt {attempt + 1}/{max_attempts})...")
                            await asyncio.sleep(0.5)
                            continue
                        return None
                    elif response.status_code == 401:
                        if token_entry:
                            await token_manager.mark_expired(token_entry.token)
                            continue
                        return None

                    response.raise_for_status()
                    res_data = response.json()
                    if "errors" in res_data:
                        logger.warning(f"GraphQL returned errors: {res_data['errors']}")
                    return res_data.get("data")
                except Exception as e:
                    logger.error(f"Error fetching GraphQL API: {e}")
                    return None

        return None

    async def fetch_repositories_graphql(self, query: str = "stars:>10000", max_repos: int = 5):
        """
        Cào toàn bộ thông tin Repositories, Owner, Commits, PRs, và Files cấu hình chỉ với 1 Query GraphQL.
        """
        graphql_query = """
        query SearchRepos($query: String!, $first: Int!) {
          search(query: $query, type: REPOSITORY, first: $first) {
            nodes {
              ... on Repository {
                databaseId
                name
                nameWithOwner
                description
                url
                stargazerCount
                forkCount
                createdAt
                updatedAt
                pushedAt
                visibility
                primaryLanguage {
                  name
                }
                openIssues: issues(states: OPEN) {
                  totalCount
                }
                owner {
                  login
                  avatarUrl
                  url
                  ... on User {
                    company
                    location
                    bio
                    followers {
                      totalCount
                    }
                    following {
                      totalCount
                    }
                    repositories {
                      totalCount
                    }
                  }
                }
                defaultBranchRef {
                  target {
                    ... on Commit {
                      history(first: 5) {
                        nodes {
                          oid
                          message
                          committedDate
                          author {
                            name
                          }
                        }
                      }
                    }
                  }
                }
                pullRequests(states: [OPEN, CLOSED, MERGED], first: 5) {
                  nodes {
                    number
                    title
                    state
                    createdAt
                    mergedAt
                    author {
                      login
                    }
                  }
                }
                packageJson: object(expression: "HEAD:package.json") {
                  ... on Blob {
                    text
                  }
                }
                requirementsTxt: object(expression: "HEAD:requirements.txt") {
                  ... on Blob {
                    text
                  }
                }
              }
            }
          }
        }
        """
        variables = {"query": query, "first": max_repos}
        data = await self.fetch_graphql(graphql_query, variables)

        if data and "search" in data and "nodes" in data["search"]:
            nodes = [n for n in data["search"]["nodes"] if n]
            msg = f"[GRAPHQL API v4] Successfully fetched {len(nodes)} repositories in 1 single HTTP call!"
            print(msg)
            logger.info(msg)
            return nodes

        return None


    async def fetch_rate_limit(self) -> int | None:
        token_entry = await token_manager.get_active_token()
        token_str = token_entry.token if token_entry else settings.GITHUB_ACCESS_TOKEN
        headers = self.get_headers(token_str=token_str)
        async with self._create_client(timeout=10.0) as client:
            try:
                response = await client.get(f"{self.base_url}/rate_limit", headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    core = data.get("resources", {}).get("core", {})
                    remaining = core.get("remaining")
                    if token_entry and remaining is not None:
                        reset_ts = core.get("reset")
                        await token_manager.update_quota(token_entry.token, remaining, core.get("limit", 5000), reset_ts)
                    return remaining
                return None
            except Exception:
                return None


github_client = GithubClient()

