"""SIGTERM (docker stop) должен приводить к финальному сбросу батчей."""
import asyncio
import os
import signal
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

import okx_hft.run as run


@pytest.mark.skipif(sys.platform == "win32", reason="add_signal_handler недоступен на Windows")
@pytest.mark.asyncio
async def test_sigterm_triggers_final_flush(monkeypatch):
    started = asyncio.Event()

    async def run_forever():
        started.set()
        await asyncio.Event().wait()

    async def fake_metrics_server(port):
        await asyncio.Event().wait()

    client = MagicMock()
    client.run_forever = run_forever
    client.periodic_flush = AsyncMock()
    client.flush_all_handlers = AsyncMock()
    client.storage = None

    monkeypatch.setattr(run, "OKXWebSocketClient", lambda settings: client)
    monkeypatch.setattr(run, "run_metrics_server", fake_metrics_server)

    task = asyncio.create_task(run.main())
    await asyncio.wait_for(started.wait(), timeout=2)

    os.kill(os.getpid(), signal.SIGTERM)

    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=5)

    client.flush_all_handlers.assert_awaited()
