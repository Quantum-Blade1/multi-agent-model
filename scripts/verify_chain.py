"""Verify the audit hash chain from the configured backend."""

from __future__ import annotations

import asyncio

from audit.store import get_audit_store


async def main() -> None:
    store = await get_audit_store()
    result = await store.verify_chain()
    print(result.model_dump_json(indent=2))
    await store.close()


if __name__ == "__main__":
    asyncio.run(main())
