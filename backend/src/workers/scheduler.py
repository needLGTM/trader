import logging
import os
import time

import httpx
from apscheduler.schedulers.background import BackgroundScheduler

log = logging.getLogger(__name__)

scheduler = BackgroundScheduler()
SYNC_INTERVAL_MINUTES = int(os.getenv("SYNC_INTERVAL_MINUTES", "5"))
STRATEGY_INTERVAL_MINUTES = int(os.getenv("STRATEGY_INTERVAL_MINUTES", "60"))
API_BASE = os.getenv("API_BASE_URL", "http://api:8000")


@scheduler.scheduled_job("interval", minutes=SYNC_INTERVAL_MINUTES)
def sync_trading_data():
    try:
        r = httpx.post(f"{API_BASE}/sync", timeout=60)
        r.raise_for_status()
        data = r.json()
        log.info(
            "state sync completed: orders=%s executions=%s positions=%s pnls=%s",
            len(data.get("orders", [])),
            len(data.get("executions", [])),
            len(data.get("positions", [])),
            len(data.get("pnls", [])),
        )
    except Exception as exc:
        log.warning("state sync failed: %s", exc)


@scheduler.scheduled_job("interval", minutes=STRATEGY_INTERVAL_MINUTES)
def run_strategy_autopilot():
    """The API performs all risk checks; this worker never talks to a broker."""
    try:
        r = httpx.post(f"{API_BASE}/autopilot/run", timeout=60)
        r.raise_for_status()
        log.info("strategy autopilot completed: %s", r.json().get("results", []))
    except Exception as exc:
        log.warning("strategy autopilot failed: %s", exc)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scheduler.start()
    while True:
        time.sleep(10)
