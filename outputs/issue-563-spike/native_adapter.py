"""Reference runner for a single fixed batch, not a general workflow engine."""

import asyncio

from core import RunView, Service


class NativeRunner:
    def __init__(self, service: Service):
        self.service = service

    async def tick(self, run_id: str) -> RunView:
        store = self.service.store
        plan = store.plan(run_id)
        if not store.approved(run_id, plan.digest):
            return store.view(run_id)
        limit = asyncio.Semaphore(2)

        async def child(topic_id: str) -> None:
            async with limit:
                await self.service.execute(run_id, plan.digest, topic_id)

        await asyncio.gather(*(child(topic.id) for topic in plan.topics))
        return store.view(run_id)
