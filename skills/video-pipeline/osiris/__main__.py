"""Allow running osiris package directly: python -m osiris"""

import asyncio
from osiris.competitor_scraper import _cli_main

if __name__ == "__main__":
    asyncio.run(_cli_main())
