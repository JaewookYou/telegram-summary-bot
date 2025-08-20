from __future__ import annotations

import asyncio

from app.run import main
import logging
import sys


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted by user")
    except Exception:
        # If logging was configured in main(), this will go to logs/error.log as well
        logging.exception("Fatal error: application crashed")
        print("Fatal error occurred. See logs/error.log for details.")
        sys.exit(1)


