import asyncio
import json
import logging
import os
import sys

# Add parent dir to path so we can import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.core.github_client import github_client
from app.services.data_cleaner import DataCleaner

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_crawler_and_save_to_json(query="stars:>10000", max_repos=2, output_file=None):
    if output_file is None:
        output_file = os.path.join(os.path.dirname(__file__), "crawled_data.json")
    logger.info(f"Starting advanced crawler for {query}")

    
    # 1. Fetch repositories
    raw_repos = await github_client.fetch_repositories(query=query, max_pages=1)
    raw_repos = raw_repos[:max_repos] # Limit for demo
    
    final_data = []
    
    for repo in raw_repos:
        owner = repo["owner"]["login"]
        repo_name = repo["name"]
        logger.info(f"Processing repository: {owner}/{repo_name}")
        
        # 2. Fetch User Profile
        raw_user = await github_client.fetch_user(owner)
        clean_user = DataCleaner.process_user(raw_user)
        
        # 3. Fetch Metrics (Commits, PRs, Issues)
        raw_commits = await github_client.fetch_repo_commits(owner, repo_name, per_page=5)
        clean_commits = [DataCleaner.process_commit(c) for c in raw_commits] if raw_commits else []
        
        raw_prs = await github_client.fetch_repo_pulls(owner, repo_name, per_page=5)
        clean_prs = [DataCleaner.process_pr(pr) for pr in raw_prs] if raw_prs else []
        
        raw_issues = await github_client.fetch_repo_issues(owner, repo_name, per_page=5)
        clean_issues = [DataCleaner.process_issue(issue) for issue in raw_issues if "pull_request" not in issue] if raw_issues else []
        
        # 4. Fetch Config Files for Framework Detection
        package_json = await github_client.fetch_repo_file_content(owner, repo_name, "package.json")
        requirements_txt = await github_client.fetch_repo_file_content(owner, repo_name, "requirements.txt")
        # Find any csproj if possible (simplified here as fetching specific file)
        # csproj = await github_client.fetch_repo_file_content(owner, repo_name, f"{repo_name}.csproj")
        
        frameworks = DataCleaner.detect_frameworks(package_json, None, requirements_txt)
        
        # 5. Assemble Final Repo Data
        metrics = {
            "commits": clean_commits,
            "pulls": clean_prs,
            "issues": clean_issues
        }
        clean_repo = DataCleaner.process_repo(repo, clean_user, frameworks, metrics)
        
        final_data.append(clean_repo)
        
    # 6. Save to JSON
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(final_data, f, ensure_ascii=False, indent=4)
        
    logger.info(f"Successfully saved {len(final_data)} repositories to {output_file}")

if __name__ == "__main__":
    asyncio.run(run_crawler_and_save_to_json())
