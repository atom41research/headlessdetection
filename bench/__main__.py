"""Entry point: uv run python -m bench"""

import asyncio

from .benchmark import main

if __name__ == "__main__":
    asyncio.run(main())
