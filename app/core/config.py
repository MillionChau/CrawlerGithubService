import os
from typing import List, Optional
from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load .env into os.environ to enable dynamic key discovery (AI_API_KEY_2, etc.)
load_dotenv()


class Settings(BaseSettings):
    PROJECT_NAME: str = "DevRadar AI & Github Crawler Service"
    API_V1_STR: str = "/api/v1"
    
    # Database
    DATABASE_URL: str = "sqlite:///./crawler.db"
    MONGODB_URL: str = "mongodb+srv://shopee-sentiment:MChau2506@cluster0.qlbix.mongodb.net/github-crawler"
    MONGODB_DB_NAME: str = "github-crawler"
    # Github API
    GITHUB_API_URL: str = "https://api.github.com"
    GITHUB_ACCESS_TOKEN: Optional[str] = None
    GITHUB_ACCESS_TOKEN_2: Optional[str] = None
    GITHUB_ACCESS_TOKENS: Optional[str] = None
    
    # Crawler Settings
    CRAWL_INTERVAL_HOURS: int = 24

    # External AI / LLM Gateway Config (UnoRouter / OpenAI-compatible API)
    EXTERNAL_AI_ENABLED: bool = True
    AI_API_KEY: Optional[str] = None
    AI_API_KEY_2: Optional[str] = None
    AI_API_KEYS: Optional[str] = None
    AI_BASE_URL: str = "https://api.unorouter.com/v1"
    AI_MODEL: str = "qwen2.5-coder-32b:free"
    AI_TIMEOUT_SECONDS: float = 25.0
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def get_initial_tokens(self) -> List[str]:
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
        for k, v in os.environ.items():
            if k.startswith("GITHUB_ACCESS_TOKEN") and v and v.strip():
                clean_v = v.strip()
                if clean_v not in tokens:
                    tokens.append(clean_v)
        return tokens

    def get_ai_keys(self) -> List[str]:
        """
        Thu thập toàn bộ danh sách khóa AI API Key từ cấu hình và biến môi trường
        (hỗ trợ phân tách dấu phẩy hoặc dạng AI_API_KEY_2, AI_API_KEY_3...) phục vụ xoay vòng khóa (Key Swap).
        """
        keys: List[str] = []
        if self.AI_API_KEYS:
            for k in self.AI_API_KEYS.split(","):
                k = k.strip()
                if k and k not in keys:
                    keys.append(k)
        if self.AI_API_KEY:
            for k in self.AI_API_KEY.split(","):
                k = k.strip()
                if k and k not in keys:
                    keys.append(k)
        # Quét thêm tất cả các biến dạng AI_API_KEY_2, AI_API_KEY_3...
        for env_k, env_v in os.environ.items():
            if env_k.startswith("AI_API_KEY") and env_v and env_v.strip():
                clean_val = env_v.strip()
                if clean_val not in keys:
                    keys.append(clean_val)
        return keys

=======
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )
>>>>>>> Stashed changes

settings = Settings()
