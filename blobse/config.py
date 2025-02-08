import logging

from fastapi_plugins import RedisSettings
from loguru_logging_intercept import setup_loguru_logging_intercept
from pydantic.class_validators import validator
from uvicorn_loguru_integration import UVICORN_LOGGING_MODULES


class Settings(RedisSettings):
    debug: bool = False

    server_url: str  # ie. https://foo.com
    redis_host: str = "0.0.0.0"
    redis_port: int = 6379
    redis_decode_responses: bool = False

    @validator('server_url', pre=True, always=True)
    def normalize_server_url(cls, v):
        return v.rstrip('/')

    class Config:
        env_file = ".env"


config = Settings()
setup_loguru_logging_intercept(
    logging.DEBUG if config.debug else logging.INFO,
    UVICORN_LOGGING_MODULES
)
