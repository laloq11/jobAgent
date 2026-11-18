"""Offline tests. core/config.py builds Settings() at import time, so dummy
Notion values are set before anything imports it (real env vars win)."""
import os

os.environ.setdefault("NOTION_TOKEN", "test-token")
os.environ.setdefault("NOTION_DB_ID", "test-db")
