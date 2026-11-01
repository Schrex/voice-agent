"""Run Alembic programmatically against an explicit database URL (used by tests)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _config(url: str) -> Config:
    config = Config(str(_INI))
    # configparser treats % as interpolation; escape it so passwords with % survive.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    command.upgrade(_config(url), revision)


def downgrade(url: str, revision: str) -> None:
    command.downgrade(_config(url), revision)
