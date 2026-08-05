import logging
import datetime
from sqlalchemy.orm import Session
from app.services.clients.github_client import github_client
from app.services.data_cleaner import DataCleaner
from app.services.extractors.structure_scanner import StructureScanner
from app.services.extractors.framework_engine import FrameworkRuleEngine
from app.services.analyzers.metrics_calculator import MetricsCalculator
from app.db import models

logger = logging.getLogger(__name__)

class CrawlerPipeline:
    def __init__(self, db: Session):
        self.db = db

    async def execute(self, query: str = "stars:>1000", max_repos: int = 1) -> dict:
        """
        Execute the 10-level crawling pipeline
        """
        logger.info(f"Starting Multi-Level Pipeline for query: {query}")
        
        # Level 1: Discovery
        raw_repos = await github_client.fetch_repositories(query=query, max_pages=1)
        raw_repos = raw_repos[:max_repos]
        
        results = []
        for raw_repo in raw_repos:
            owner = raw_repo["owner"]["login"]
            repo_name = raw_repo["name"]
            logger.info(f"Processing Repo: {owner}/{repo_name}")
            
            # Level 2: Owner & Contributors
            raw_user = await github_client.fetch_user(owner)
            clean_user = DataCleaner.process_user(raw_user)
            contributors = await github_client.fetch_contributors(owner, repo_name)
            
            # Level 3: Activity
            raw_commits = await github_client.fetch_repo_commits(owner, repo_name, per_page=5)
            clean_commits = [DataCleaner.process_commit(c) for c in raw_commits] if raw_commits else []
            
            raw_prs = await github_client.fetch_repo_pulls(owner, repo_name, per_page=5)
            clean_prs = [DataCleaner.process_pr(pr) for pr in raw_prs] if raw_prs else []
            
            raw_issues = await github_client.fetch_repo_issues(owner, repo_name, per_page=5)
            clean_issues = [DataCleaner.process_issue(iss) for iss in raw_issues if "pull_request" not in iss] if raw_issues else []
            
            # Level 4: Structure Scanning
            tree_data = await github_client.fetch_repo_tree(owner, repo_name, raw_repo.get("default_branch", "main"))
            structure_data = StructureScanner.scan_tree(tree_data)
            
            # Level 5 & 8: File Analysis & Docs
            files_to_fetch = ["package.json", "requirements.txt", "pom.xml"] # simplified
            # Add csproj if needed
            file_contents = {}
            for f in files_to_fetch:
                if f in structure_data.get("important_files", []):
                    file_contents[f] = await github_client.fetch_repo_file_content(owner, repo_name, f)
            
            # Level 6: Framework Engine
            fw_detection = FrameworkRuleEngine.detect(file_contents)
            
            # Level 7: CI/CD Detection
            cicd_data = StructureScanner.detect_cicd(structure_data)
            
            # Level 9: Releases
            releases = await github_client.fetch_releases(owner, repo_name)
            
            # Assemble & Calculate Health Score
            activity_data = {"commits": clean_commits, "issues": clean_issues, "pulls": clean_prs}
            repo_metrics_data = {"contributors": contributors, "forks": raw_repo.get("forks_count", 0)}
            scores = MetricsCalculator.calculate_health_score(repo_metrics_data, activity_data, structure_data)
            
            clean_repo = DataCleaner.process_repo(raw_repo, clean_user, fw_detection.get("frameworks", []), activity_data)
            clean_repo["scores"] = scores
            clean_repo["cicd"] = cicd_data
            clean_repo["language_detected"] = fw_detection.get("language")
            
            # Save to Database (Level 10 logic embedded in save)
            self._save_to_db(clean_repo, clean_user, scores, fw_detection)
            
            results.append(clean_repo)
            
        return results

    def _save_to_db(self, repo_data: dict, user_data: dict, scores: dict, fw_detection: dict):
        try:
            # Upsert User
            user_id = str(repo_data["owner"]["username"]) # Using username as id for simplicity in demo
            user = self.db.query(models.GithubUser).filter(models.GithubUser.id == user_id).first()
            if not user:
                user = models.GithubUser(id=user_id, username=user_data.get("username"), company=user_data.get("company"))
                self.db.add(user)
                
            # Upsert Repo
            repo_id = repo_data["id"]
            repo = self.db.query(models.GithubRepository).filter(models.GithubRepository.id == repo_id).first()
            if not repo:
                repo = models.GithubRepository(
                    id=repo_id, owner_id=user_id, name=repo_data["name"], 
                    full_name=repo_data["full_name"], description=repo_data["description"],
                    stars=repo_data["stars"], forks=repo_data["forks"],
                    primary_language=fw_detection.get("language")
                )
                self.db.add(repo)
            
            # Add Metrics
            metrics = models.RepositoryMetrics(
                repo_id=repo_id,
                activity_score=scores["activity_score"],
                maintenance_score=scores["maintenance_score"],
                community_score=scores["community_score"],
                quality_score=scores["quality_score"],
                health_score=scores["health_score"]
            )
            self.db.add(metrics)
            
            # Add Frameworks
            for fw in fw_detection.get("frameworks", []):
                self.db.add(models.GithubFramework(repo_id=repo_id, framework=fw["name"]))
                
            self.db.commit()
            logger.info(f"Saved {repo_data['full_name']} to DB successfully")
        except Exception as e:
            self.db.rollback()
            logger.error(f"Error saving to DB: {e}")
