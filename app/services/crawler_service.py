import datetime
import logging
from sqlalchemy.orm import Session
from app.db.models import CrawlJob, GithubRepository
from app.core.github_client import github_client
from app.services.data_cleaner import DataCleaner

logger = logging.getLogger(__name__)

class CrawlerService:
    @staticmethod
    async def run_crawl_job(db: Session, job_id: str, query: str = "stars:>500"):
        """
        Main logic to execute the crawl job in background
        """
        job = db.query(CrawlJob).filter(CrawlJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found.")
            return

        try:
            logger.info(f"Starting crawl job {job_id} with query: {query}")
            raw_repos = await github_client.fetch_repositories(query=query, max_pages=2) # Max pages limited for demo
            
            processed_count = 0
            for raw_repo in raw_repos:
                cleaned_data = DataCleaner.process_repo_data(raw_repo)
                
                # Check if exists
                repo_id = cleaned_data['id']
                existing_repo = db.query(GithubRepository).filter(GithubRepository.id == repo_id).first()
                
                if existing_repo:
                    # Update
                    for key, value in cleaned_data.items():
                        setattr(existing_repo, key, value)
                else:
                    # Insert
                    new_repo = GithubRepository(**cleaned_data)
                    db.add(new_repo)
                    
                processed_count += 1
            
            db.commit()
            
            # Mark job as success
            job.status = "SUCCESS"
            job.records_processed = processed_count
            job.end_time = datetime.datetime.utcnow()
            db.commit()
            logger.info(f"Crawl job {job_id} completed successfully. Processed: {processed_count}")
            
        except Exception as e:
            logger.error(f"Crawl job {job_id} failed: {str(e)}")
            job.status = "FAILED"
            job.error_message = str(e)
            job.end_time = datetime.datetime.utcnow()
            db.commit()
