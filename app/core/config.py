from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "DevRadar AI & Github Crawler Service"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:///./crawler.db"
    MONGODB_URL: str = "mongodb+srv://shopee-sentiment:MChau2506@cluster0.qlbix.mongodb.net/github-crawler"
    MONGODB_DB_NAME: str = "github-crawler"

    
    # Github API
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_ACCESS_TOKEN: str | None = None
    GITHUB_ACCESS_TOKENS: str | None = None
    
    # Crawler Settings
    CRAWL_INTERVAL_HOURS: int = 24
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_initial_tokens(self) -> list[str]:
        tokens = []
        if self.GITHUB_ACCESS_TOKENS:
            for t in self.GITHUB_ACCESS_TOKENS.split(","):
                t = t.strip()
                if t and t not in tokens:
                    tokens.append(t)
        if self.GITHUB_ACCESS_TOKEN:
            for t in self.GITHUB_ACCESS_TOKEN.split(","):
                t = t.strip()
                if t and t not in tokens:
                    tokens.append(t)
        # Quét thêm tất cả các biến dạng GITHUB_ACCESS_TOKEN_2, GITHUB_ACCESS_TOKEN_3...
        import os
        for k, v in os.environ.items():
            if k.startswith("GITHUB_ACCESS_TOKEN") and v and v.strip():
                clean_v = v.strip()
                if clean_v not in tokens:
                    tokens.append(clean_v)
        return tokens

settings = Settings()
