import logging
import time

from app.order_service import execute_pending_orders

logging.basicConfig(level=logging.INFO, format="[order_executor] %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    while True:
        try:
            count = execute_pending_orders()
            if count:
                log.info("executed %s pending orders", count)
        except Exception:
            log.exception("order execution loop failed")
        time.sleep(2)


if __name__ == "__main__":
    main()