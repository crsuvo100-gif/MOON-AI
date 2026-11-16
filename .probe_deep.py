import asyncio
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def go():
    o = Orchestrator(get_settings())
    await o.setup()
    # Lock is always-unlocked (design); observe returns None. Treat as unlocked.
    notice = o._lock.observe('MOON love you 3000')
    print('observe() returned:', repr(notice))
    res = await o._tools.run('system_info', {}, agent=None)
    print('system_info result (first 200 chars):', repr((res.output or '')[:200]))
    assert 'linux' in (res.output or ''), 'system_info did not report linux!'
    print('DEEP_PROOF_OK: system_info returned linux')
    await o.teardown()

asyncio.run(go())
