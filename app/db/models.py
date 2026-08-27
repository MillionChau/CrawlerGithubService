from sqlalchemy import Column, Integer, String, DateTime, Text, Float, ForeignKey, JSON
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base


class RepositoryModel(Base):
    __tablename__ = "repositories"

    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True)
    name = Column(String, index=True)
    full_name = Column(String, index=True)
    owner = Column(String)
    html_url = Column(String)
    description = Column(Text, nullable=True)
    language = Column(String, nullable=True)
    stargazers_count = Column(Integer, default=0)
    forks_count = Column(Integer, default=0)
    open_issues_count = Column(Integer, default=0)
    frameworks = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class UserModel(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    login = Column(String, unique=True, index=True)
    avatar_url = Column(String, nullable=True)
    html_url = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    public_repos = Column(Integer, default=0)
    followers = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class MetricModel(Base):
    __tablename__ = "metrics"

    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(Integer, ForeignKey("repositories.id"))
    metric_key = Column(String, index=True)
    metric_value = Column(Float, default=0.0)
    extra_info = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
