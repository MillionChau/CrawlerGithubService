import re
import json
from datetime import datetime, timezone, timedelta

class DataCleaner:
    @staticmethod
    def clean_text(text: str) -> str:
        if not text:
            return ""
        text = text.replace('\x00', '')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @staticmethod
    def detect_frameworks(package_json_content: str, csproj_content: str, requirements_txt: str) -> list:
        frameworks = set()
        
        # Parse package.json
        if package_json_content:
            try:
                data = json.loads(package_json_content)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if "react" in deps: frameworks.add("React")
                if "next" in deps: frameworks.add("Next.js")
                if "vue" in deps: frameworks.add("Vue")
                if "@angular/core" in deps: frameworks.add("Angular")
                if "@nestjs/core" in deps: frameworks.add("NestJS")
            except:
                pass
                
        # Parse requirements.txt
        if requirements_txt:
            reqs = requirements_txt.lower()
            if "django" in reqs: frameworks.add("Django")
            if "fastapi" in reqs: frameworks.add("FastAPI")
            if "tensorflow" in reqs: frameworks.add("TensorFlow")
            if "torch" in reqs: frameworks.add("PyTorch")
            
        # Parse csproj
        if csproj_content:
            content = csproj_content.lower()
            if "microsoft.aspnetcore" in content: frameworks.add("ASP.NET Core")
            if "microsoft.entityframeworkcore" in content: frameworks.add("Entity Framework")
            if "microsoft.aspnetcore.components.webassembly" in content: frameworks.add("Blazor")
            
        return list(frameworks)

    @staticmethod
    def process_user(raw_user: dict) -> dict:
        if not raw_user: return {}
        return {
            "username": DataCleaner.clean_text(raw_user.get("login")),
            "followers": raw_user.get("followers", 0),
            "following": raw_user.get("following", 0),
            "public_repos": raw_user.get("public_repos", 0),
            "company": DataCleaner.clean_text(raw_user.get("company")),
            "location": DataCleaner.clean_text(raw_user.get("location")),
            "created_at": raw_user.get("created_at")
        }

    @staticmethod
    def process_commit(raw_commit: dict) -> dict:
        commit_data = raw_commit.get("commit", {})
        author_data = commit_data.get("author", {})
        return {
            "sha": raw_commit.get("sha"),
            "author": DataCleaner.clean_text(author_data.get("name")),
            "date": author_data.get("date"),
            "message": DataCleaner.clean_text(commit_data.get("message"))
        }

    @staticmethod
    def process_pr(raw_pr: dict) -> dict:
        return {
            "number": raw_pr.get("number"),
            "title": DataCleaner.clean_text(raw_pr.get("title")),
            "state": raw_pr.get("state"),
            "author": DataCleaner.clean_text(raw_pr.get("user", {}).get("login")),
            "created_at": raw_pr.get("created_at"),
            "merged_at": raw_pr.get("merged_at")
        }

    @staticmethod
    def process_issue(raw_issue: dict) -> dict:
        # PRs are also considered issues in Github API, filter them out if needed
        return {
            "number": raw_issue.get("number"),
            "title": DataCleaner.clean_text(raw_issue.get("title")),
            "state": raw_issue.get("state"),
            "author": DataCleaner.clean_text(raw_issue.get("user", {}).get("login")),
            "created_at": raw_issue.get("created_at"),
            "closed_at": raw_issue.get("closed_at")
        }

    @staticmethod
    def compute_activity_and_maturity(commits: list, pulls: list, created_at_str: str) -> tuple:
        """
        Tính toán các trường phái sinh (derived fields) phục vụ đo lường Flow & Age:
        - is_mature: created_at <= now - 30 days
        - activity_stats: commits_90d, has_commit_90d, last_commit_date, prs_merged_90d
        """
        now = datetime.now(timezone.utc)
        d30 = now - timedelta(days=30)
        d90 = now - timedelta(days=90)

        is_mature = True
        if created_at_str:
            try:
                c_dt = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                is_mature = (c_dt <= d30)
            except Exception:
                is_mature = True

        commits_90d = 0
        last_commit_date = None
        for c in (commits or []):
            c_date_str = c.get("date")
            if not c_date_str and isinstance(c.get("commit"), dict):
                c_date_str = c.get("commit", {}).get("author", {}).get("date")
            if c_date_str:
                if not last_commit_date or c_date_str > last_commit_date:
                    last_commit_date = c_date_str
                try:
                    c_dt = datetime.fromisoformat(c_date_str.replace('Z', '+00:00'))
                    if c_dt >= d90:
                        commits_90d += 1
                except Exception:
                    pass

        prs_merged_90d = 0
        for p in (pulls or []):
            m_date_str = p.get("merged_at") or p.get("mergedAt")
            if m_date_str:
                try:
                    m_dt = datetime.fromisoformat(m_date_str.replace('Z', '+00:00'))
                    if m_dt >= d90:
                        prs_merged_90d += 1
                except Exception:
                    pass

        activity_stats = {
            "commits_90d": commits_90d,
            "has_commit_90d": commits_90d > 0,
            "last_commit_date": last_commit_date,
            "prs_merged_90d": prs_merged_90d
        }
        return is_mature, activity_stats

    @staticmethod
    def process_repo(raw_repo: dict, owner_data: dict, frameworks: list, metrics: dict) -> dict:
        created_at_val = raw_repo.get("created_at")
        commits_list = metrics.get("commits", [])
        pulls_list = metrics.get("pulls", [])
        is_mature, act_stats = DataCleaner.compute_activity_and_maturity(commits_list, pulls_list, created_at_val)

        return {
            "id": str(raw_repo.get("id")),
            "name": DataCleaner.clean_text(raw_repo.get("name")),
            "full_name": DataCleaner.clean_text(raw_repo.get("full_name")),
            "description": DataCleaner.clean_text(raw_repo.get("description")),
            "primary_language": raw_repo.get("language", "Unknown"),
            "stars": raw_repo.get("stargazers_count", 0),
            "forks": raw_repo.get("forks_count", 0),
            "open_issues": raw_repo.get("open_issues_count", 0),
            "visibility": raw_repo.get("visibility"),
            "created_at": created_at_val,
            "updated_at": raw_repo.get("updated_at"),
            "pushed_at": raw_repo.get("pushed_at") or raw_repo.get("updated_at"),
            "is_fork": bool(raw_repo.get("fork", False)),
            "is_archived": bool(raw_repo.get("archived", False)),
            "is_mature": is_mature,
            "activity_stats": act_stats,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "owner": owner_data,
            "detected_frameworks": frameworks,
            "recent_commits": commits_list,
            "recent_pull_requests": pulls_list,
            "recent_issues": metrics.get("issues", [])
        }

    @staticmethod
    def process_graphql_repo(node: dict) -> dict:
        """
        Chuyển đổi dữ liệu 1 GraphQL Repository Node về chuẩn Dict Schema của DevRadar.
        """
        if not node:
            return {}

        database_id = node.get("databaseId") or node.get("id", "0")
        name = DataCleaner.clean_text(node.get("name"))
        full_name = DataCleaner.clean_text(node.get("nameWithOwner")) or name
        description = DataCleaner.clean_text(node.get("description"))
        
        lang_node = node.get("primaryLanguage")
        primary_language = lang_node.get("name") if lang_node else "Unknown"

        stars = node.get("stargazerCount", 0)
        forks = node.get("forkCount", 0)

        open_issues_node = node.get("openIssues")
        open_issues = open_issues_node.get("totalCount", 0) if isinstance(open_issues_node, dict) else 0

        # Owner Processing
        owner_raw = node.get("owner") or {}
        followers_node = owner_raw.get("followers") or {}
        followers_count = followers_node.get("totalCount", 0) if isinstance(followers_node, dict) else 0
        repos_node = owner_raw.get("repositories") or {}
        public_repos_count = repos_node.get("totalCount", 0) if isinstance(repos_node, dict) else 0

        owner_data = {
            "username": DataCleaner.clean_text(owner_raw.get("login")),
            "followers": followers_count,
            "public_repos": public_repos_count,
            "company": DataCleaner.clean_text(owner_raw.get("company")),
            "location": DataCleaner.clean_text(owner_raw.get("location")),
            "bio": DataCleaner.clean_text(owner_raw.get("bio"))
        }

        # Commits Processing
        clean_commits = []
        dbr = node.get("defaultBranchRef") or {}
        target = dbr.get("target") or {} if isinstance(dbr, dict) else {}
        history = (target.get("history") or {}).get("nodes", []) if isinstance(target, dict) else []
        for c in (history or []):
            if not isinstance(c, dict):
                continue
            c_author = c.get("author") or {}
            clean_commits.append({
                "sha": c.get("oid"),
                "author": DataCleaner.clean_text(c_author.get("name") if isinstance(c_author, dict) else None),
                "date": c.get("committedDate"),
                "message": DataCleaner.clean_text(c.get("message"))
            })

        # Pull Requests Processing
        clean_prs = []
        prs_nodes = (node.get("pullRequests") or {}).get("nodes", [])
        for pr in (prs_nodes or []):
            if not isinstance(pr, dict):
                continue
            pr_author = pr.get("author") or {}
            clean_prs.append({
                "number": pr.get("number"),
                "title": DataCleaner.clean_text(pr.get("title")),
                "state": pr.get("state"),
                "author": DataCleaner.clean_text(pr_author.get("login") if isinstance(pr_author, dict) else None),
                "created_at": pr.get("createdAt"),
                "merged_at": pr.get("mergedAt")
            })

        # Framework Detection
        pkg_text = node.get("packageJson", {}).get("text") if isinstance(node.get("packageJson"), dict) else None
        req_text = node.get("requirementsTxt", {}).get("text") if isinstance(node.get("requirementsTxt"), dict) else None
        frameworks = DataCleaner.detect_frameworks(pkg_text, None, req_text)

        created_at_val = node.get("createdAt")
        is_mature, act_stats = DataCleaner.compute_activity_and_maturity(clean_commits, clean_prs, created_at_val)

        return {
            "id": str(database_id),
            "name": name,
            "full_name": full_name,
            "description": description,
            "primary_language": primary_language,
            "stars": stars,
            "forks": forks,
            "open_issues": open_issues,
            "visibility": node.get("visibility", "PUBLIC"),
            "created_at": created_at_val,
            "updated_at": node.get("updatedAt"),
            "pushed_at": node.get("pushedAt") or node.get("updatedAt"),
            "is_fork": bool(node.get("isFork", False)),
            "is_archived": bool(node.get("isArchived", False)),
            "is_mature": is_mature,
            "activity_stats": act_stats,
            "last_synced_at": datetime.now(timezone.utc).isoformat(),
            "owner": owner_data,
            "detected_frameworks": frameworks,
            "recent_commits": clean_commits,
            "recent_pull_requests": clean_prs,
            "recent_issues": []
        }

