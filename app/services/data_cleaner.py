import re
import json

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
    def process_repo(raw_repo: dict, owner_data: dict, frameworks: list, metrics: dict) -> dict:
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
            "created_at": raw_repo.get("created_at"),
            "updated_at": raw_repo.get("updated_at"),
            "owner": owner_data,
            "detected_frameworks": frameworks,
            "recent_commits": metrics.get("commits", []),
            "recent_pull_requests": metrics.get("pulls", []),
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
        owner_raw = node.get("owner", {})
        followers_node = owner_raw.get("followers", {})
        followers_count = followers_node.get("totalCount", 0) if isinstance(followers_node, dict) else 0
        repos_node = owner_raw.get("repositories", {})
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
        target = node.get("defaultBranchRef", {}).get("target", {}) if node.get("defaultBranchRef") else {}
        history = target.get("history", {}).get("nodes", []) if isinstance(target, dict) else []
        for c in history:
            clean_commits.append({
                "sha": c.get("oid"),
                "author": DataCleaner.clean_text(c.get("author", {}).get("name")),
                "date": c.get("committedDate"),
                "message": DataCleaner.clean_text(c.get("message"))
            })

        # Pull Requests Processing
        clean_prs = []
        prs_nodes = node.get("pullRequests", {}).get("nodes", [])
        for pr in prs_nodes:
            clean_prs.append({
                "number": pr.get("number"),
                "title": DataCleaner.clean_text(pr.get("title")),
                "state": pr.get("state"),
                "author": DataCleaner.clean_text(pr.get("author", {}).get("login")),
                "created_at": pr.get("createdAt"),
                "merged_at": pr.get("mergedAt")
            })

        # Framework Detection
        pkg_text = node.get("packageJson", {}).get("text") if isinstance(node.get("packageJson"), dict) else None
        req_text = node.get("requirementsTxt", {}).get("text") if isinstance(node.get("requirementsTxt"), dict) else None
        frameworks = DataCleaner.detect_frameworks(pkg_text, None, req_text)

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
            "created_at": node.get("createdAt"),
            "updated_at": node.get("updatedAt"),
            "owner": owner_data,
            "detected_frameworks": frameworks,
            "recent_commits": clean_commits,
            "recent_pull_requests": clean_prs,
            "recent_issues": []
        }

