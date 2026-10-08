from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    PROJECT_NAME: str = "Bankaool SPEI Incoming Service"
    API_V1_STR: str = "/v1"
    
    # Bankaool SPEI Institution ID (ej. 148 o asignado por Banxico)
    BANKAOOL_INSTITUTION_ID: str = "148"
    
    # Redis Configuration
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: Optional[str] = None
    REDIS_DB: int = 0
    IDEMPOTENCY_TTL_SECONDS: int = 86400  # 24 horas para claves de rastreo
    
    # BigQuery Configuration
    GCP_PROJECT_ID: str = "bankaool-prod"
    BIGQUERY_DATASET: str = "spei_transactions"
    BIGQUERY_TABLE: str = "incoming_transfers"
    
    # Security / PKI
    ENFORCE_SIGNATURE_VERIFICATION: bool = True

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()
