import os

from pydantic_settings import BaseSettings, SettingsConfigDict


# Codex starts stdio servers from its own working directory, so let its MCP
# configuration point Settings at this project's env file explicitly.
_ENV_FILE = os.environ.get("GOODWE_ENV_FILE", ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore")

    goodwe_region: str = "au"
    goodwe_username: str
    goodwe_password: str
    goodwe_station_id: str
    goodwe_device_list: str = ""  # Optional JSON array of {"sn": "...", "deviceType": "..."}
    request_timeout: float = 30.0
    mcp_transport: str = "stdio"  # stdio or streamable-http
    mcp_host: str = "127.0.0.1"
    mcp_port: int = 8000

    @property
    def portal_origin(self) -> str:
        return f"https://{self.goodwe_region}-semsplus.goodwe.com"

    @property
    def api_base(self) -> str:
        return f"{self.portal_origin}/web/sems"
