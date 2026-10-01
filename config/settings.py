# config/settings.py

from functools import lru_cache
from typing import Any, Literal

from pathlib import Path

from pydantic import AliasChoices, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from sqlalchemy.engine import URL, make_url


# database dialects
_DIALECTS = {
    "mysql": ("mysql+aiomysql", 3306),
    "postgresql": ("postgresql+asyncpg", 5432),
}


class Settings(BaseSettings):
    """
    fastAPI app configurations
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True
    )

    # app configurations
    app_name: str = "BansiGo"
    app_env: Literal["development", "testing", "production"] = "development"
    debug: bool = False
    items_per_page: int = Field(20, gt=0)


    # security configurations
    secret_key: SecretStr = Field(min_length=32)
    access_tokens_expire_minutes: int = Field(30, gt=0)


    # database configurations
    database_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("database_url", "sqlalchemy_database_uri")
    )
    db_dialect: Literal["mysql", "postgresql"] = "mysql"
    db_user: str = "root"
    db_password: SecretStr = SecretStr("")
    db_host: str = "localhost"
    db_port: int | None = None
    db_name: str = ""

    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout: int = 20
    db_pool_recycle: int = 300
    db_pool_pre_ping: bool = True
    db_pool_use_lifo: bool = True
    db_echo: bool = False
    db_echo_pool: bool = False


    # mail configurations
    mail_server: str = "localhost"
    mail_port: int = 25
    mail_username: str | None = None
    mail_password: SecretStr | None = None
    mail_use_tls: bool = False
    mail_use_ssl: bool = False
    mail_default_sender: str = "no-reply@localhost"
    mail_timeout: int = 10

    mail_suppress_send: bool = False


    # verification configurations
    verification_code_length: int = Field(6, ge=4, le=10)
    verification_code_ttl_minutes: int = Field(15, gt=0)
    verification_max_attempts: int = Field(5, gt=0)
    verification_resend_cooldown_seconds: int = Field(60, ge=0)

    require_verified_email: bool = False


    # logging configurations
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_dir: Path = Path("logs")
    log_to_file: bool = True


    # validation configurations
    @model_validator(mode="after")
    def _cross_field_checks(self):
        """
        performs cross field checks for settings attributes
        :return:
        """

        if not self.database_url and not self.db_name:
            raise ValueError("Set DATABASE_URL, or DB_NAME (Include DB_USER, DB_PASSWORD, DB_HOST)")

        if self.mail_use_tls and self.mail_use_ssl:
            raise ValueError("MAIL_USE_TLS and MAIL_USE_SSL are mutually exclusive")

        if self.app_env == "production":
            if self.debug:
                raise ValueError("DEBUG must be false when APP_ENV=production")

            if self.mail_suppress_send:
                raise ValueError("MAIL_SUPPRESS_SEND must be false when APP_ENV=production")

        return self


    # derived values
    @property
    def is_production(self) -> bool:
        """
        checks if the app is in production mode
        :return: bool
        """
        return self.app_env == "production"


    @property
    def sqlalchemy_url(self) -> str | URL:
        """
        the database URL
        :return: str | URL
        """
        if self.database_url:
            return self.database_url

        driver, default_port = _DIALECTS[self.db_dialect]
        return URL.create(
            drivername=driver,
            username=self.db_user,
            password=self.db_password.get_secret_value() or None,
            host=self.db_host,
            port=self.db_port or default_port,
            database=self.db_name,
            query={"charset": "utf8mb4"} if self.db_dialect == "mysql" else {}
        )

    @property
    def engine_options(self) -> dict[str, Any]:
        """
        database engine options
        :return: dict[str, Any]
        """

        backend = make_url(self.sqlalchemy_url).get_backend_name()
        options: dict[str, Any] = {"echo": self.db_echo}

        if backend == "sqlite":
            return options

        options.update(
            pool_size = self.db_pool_size,
            max_overflow = self.db_max_overflow,
            pool_timeout = self.db_pool_timeout,
            pool_recycle = self.db_pool_recycle,
            pool_pre_ping = self.db_pool_pre_ping,
            pool_use_lifo = self.db_pool_use_lifo,
            echo_pool = self.db_echo_pool
        )

        if backend == "mysql":
            options["connect_args"] = {"init_command": "SET time_zone = '+00:00'"}

        return options

@lru_cache
def get_settings() -> Settings:
    """
    builds the settings once for reuse
    :return: Settings
    """

    return Settings()

