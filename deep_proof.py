import asyncio
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator
async def go():
    o = Orchestrator(get_settings())
    await o.setup()
    lock = o._lock
    notice = lock.observe('MOON love you 3000')
    print('unlock notice:', notice[:80])
    r = await o._tools.run('system_info', {}, agent=None)
    out = r.output if r else None
    print('system_info result head:', repr(out[:160]) if out else '(none)')
    print('HAS_LINUX:', bool(out and 'linux' in str(out)))
    await o.teardown()
asyncio.run(go())
