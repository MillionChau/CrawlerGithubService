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
