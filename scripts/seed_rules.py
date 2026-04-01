"""Seed default compliance rules into the rules backend."""

from __future__ import annotations

import asyncio

from rules.engine import get_rule_engine


async def main() -> None:
    engine = await get_rule_engine()
    await engine._load_from_dynamo()
    print("Rules loaded and defaults ensured.")
    await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
