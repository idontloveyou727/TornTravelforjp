from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from app.config import load_config
from app.logging_config import configure_logging
from app.main import run_forever
from app.once import run_once_command


LOGGER = logging.getLogger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="YATA UK item 206 restock monitor")
    parser.add_argument("--once", action="store_true", help="run one monitor cycle and exit")
    args = parser.parse_args(argv)

    if not args.once:
        run_forever()
        return 0

    try:
        config = load_config()
        configure_logging(config.log_level)
        LOGGER.info("Starting one-shot YATA restock monitor config=%s", config.safe_summary())
    except Exception:
        logging.basicConfig(level=logging.ERROR)
        LOGGER.exception("Failed to load monitor configuration")
        return 2

    return run_once_command(config)


if __name__ == "__main__":
    raise SystemExit(main())
