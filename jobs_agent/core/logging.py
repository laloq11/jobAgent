"""Structured logging: console + rotating file at logs/agent.log."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured = False
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "agent.log"


def _configure() -> None:
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(exist_ok=True)
    fmt = "%(asctime)s %(levelname)-7s %(name)s | %(message)s"
    formatter = logging.Formatter(fmt, datefmt="%Y-%m-%d %H:%M:%S")

    root = logging.getLogger("jobs_agent")
    root.setLevel(logging.INFO)
    root.propagate = False

    ch = logging.StreamHandler()
    ch.setFormatter(formatter)
    root.addHandler(ch)

    fh = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=5)
    fh.setFormatter(formatter)
    root.addHandler(fh)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    _configure()
    return logging.getLogger(f"jobs_agent.{name}")
