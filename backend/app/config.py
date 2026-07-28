from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://newsletter:newsletter@db:5434/newsletter"
    db_host: str = "db"
    db_port: int = 5432
    db_user: str = "newsletter"
    db_password: str = "newsletter"
    db_name: str = "newsletter"

    github_token: str = ""

    # Primary LLM: Qwen3.5 on difgpu01 (128k context). Default for all scoring/translation.
    llm_base_url: str = "http://difgpu01.tdc.otsuka-shokai.co.jp:9000/v1"
    llm_api_key: str = "tensorflow"
    llm_model: str = "Qwen/Qwen3.5-122B-A10B"

    # Fallback LLM: MiniMax-M3 on difgpu01 (used if the primary endpoint is down).
    llm_fallback_base_url: str = "http://difgpu01.tdc.otsuka-shokai.co.jp:9003/v1"
    llm_fallback_model: str = "MiniMaxAI/MiniMax-M3-MXFP8"

    # DISABLED — DeepSeek on macdep01:8001 must NOT be used. Kept commented for reference:
    #   llm_base_url = "http://macdep01.tdc.otsuka-shokai.co.jp:8001/v1"  (model: DeepSeek-V4-Flash / Why-LLM)

    # Secondary LiteLLM "foundry" endpoint (MiMo-V2.5) — kept available but NOT the default.
    anthropic_foundry_base_url: str = "http://macdep01.tdc.otsuka-shokai.co.jp:8008/"
    anthropic_foundry_api_key: str = ""
    foundry_model: str = "anthropic-MiMo-V2.5"

    # Public URL of the newsletter web UI (Explore/subscribe homepage), shown in emails.
    site_url: str = "http://iitgpu07.hon.otsuka-shokai.co.jp:3737/"

    smtp_host: str = "mta-fm21.otsuka-shokai.co.jp"
    smtp_port: int = 25
    sender_email: str = "chakshu@otsuka-shokai.co.jp"
    alert_email: str = "chakshu@otsuka-shokai.co.jp"
    default_recipients: str = "chakshu@otsuka-shokai.co.jp,rahil@otsuka-shokai.co.jp,naman@otsuka-shokai.co.jp"

    http_proxy: str = "http://proxy.otsuka-shokai.co.jp:8080"
    no_proxy: str = "localhost,127.0.0.1,db,difgpu01.tdc.otsuka-shokai.co.jp,macdep01.tdc.otsuka-shokai.co.jp,mta-fm21.otsuka-shokai.co.jp,mta-fm22.otsuka-shokai.co.jp,10.0.0.0/8,.otsuka-shokai.co.jp"

    cron_hour: int = 7
    cron_minute: int = 50
    top_n_items: int = 10
    dedup_window_days: int = 14

    class Config:
        env_file = ".env"


settings = Settings()
