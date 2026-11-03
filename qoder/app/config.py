"""配置加载：从环境变量或 .env 读取 seekdb 连接参数。"""

import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # 允许在没有 python-dotenv 时直接运行
    pass


@dataclass
class Settings:
    """运行配置，全部来自环境变量，便于评审复现。"""

    seekdb_host: str = os.getenv("SEEKDB_HOST", "127.0.0.1")
    seekdb_port: int = int(os.getenv("SEEKDB_PORT", "2881"))
    seekdb_user: str = os.getenv("SEEKDB_USER", "root")
    seekdb_password: str = os.getenv("SEEKDB_PASSWORD", "")
    seekdb_database: str = os.getenv("SEEKDB_DATABASE", "test")
    embedding_dim: int = int(os.getenv("EMBEDDING_DIM", "256"))
    app_port: int = int(os.getenv("APP_PORT", "8000"))


settings = Settings()