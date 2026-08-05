import datetime
import uuid
from sqlalchemy import Column, Integer, String, DateTime, Text, JSON, Float, Boolean, ForeignKey
from app.db.database import Base

class CrawlJob(Base):
    __tablename__ = "crawl_jobs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, index=True) # PENDING, RUNNING, SUCCESS, FAILED
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    records_processed = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)

class GithubUser(Base):
    __tablename__ = "github_users"
    
    id = Column(String, primary_key=True)
    username = Column(String, index=True)
    followers = Column(Integer, default=0)
    following = Column(Integer, default=0)
    public_repos = Column(Integer, default=0)
    company = Column(String, nullable=True)
    location = Column(String, nullable=True)
    account_created_at = Column(DateTime, nullable=True)
    last_synced = Column(DateTime, default=datetime.datetime.utcnow)

class GithubRepository(Base):
    __tablename__ = "github_repositories"

    id = Column(String, primary_key=True)
    owner_id = Column(String, ForeignKey("github_users.id"))
    name = Column(String, index=True)
    full_name = Column(String)
    description = Column(Text, nullable=True)
    primary_language = Column(String, index=True, nullable=True)
    stars = Column(Integer, default=0)
    forks = Column(Integer, default=0)
    open_issues = Column(Integer, default=0)
    default_branch = Column(String, default="main")
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, nullable=True)
    last_synced = Column(DateTime, default=datetime.datetime.utcnow)

class RepositoryMetrics(Base):
    __tablename__ = "repository_metrics"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(String, ForeignKey("github_repositories.id"))
    activity_score = Column(Float, default=0.0)
    maintenance_score = Column(Float, default=0.0)
    community_score = Column(Float, default=0.0)
    quality_score = Column(Float, default=0.0)
    health_score = Column(Float, default=0.0)
    measured_at = Column(DateTime, default=datetime.datetime.utcnow)

class GithubFramework(Base):
    __tablename__ = "github_frameworks"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    repo_id = Column(String, ForeignKey("github_repositories.id"))
    framework = Column(String, index=True)
    confidence_score = Column(Float, default=1.0)
    
class GithubRelease(Base):
    __tablename__ = "github_releases"
    
    id = Column(String, primary_key=True)
    repo_id = Column(String, ForeignKey("github_repositories.id"))
    version = Column(String)
    release_date = Column(DateTime)
    downloads = Column(Integer, default=0)

class TechnologyTrend(Base):
    __tablename__ = "technology_trends"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    technology_name = Column(String, index=True)
    type = Column(String) # LANGUAGE or FRAMEWORK
    snapshot_date = Column(DateTime, default=datetime.datetime.utcnow)
    total_repos = Column(Integer, default=0)
    total_stars = Column(Integer, default=0)
