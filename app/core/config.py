from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "DevRadar AI & Github Crawler Service"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:///./crawler.db"
    
    # Github API
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_ACCESS_TOKEN: str | None = None
    
    # Crawler Settings
    CRAWL_INTERVAL_HOURS: int = 24
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
