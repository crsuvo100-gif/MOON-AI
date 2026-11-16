import sys, asyncio
sys.path.insert(0, '/home/meow/Projects/MOON')
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    notice = o._lock.observe('MOON love you 3000')
    print('NOTICE:', notice)
    assert 'unlocked' in notice, 'unlock failed'
    res = await o._tools.run('system_info', {}, agent=None)
    out = str(res)
    print('TOOL_OUTPUT:', out[:400])
    assert 'linux' in out.lower(), 'linux not in output: %r' % out
    print('DEEP_PROOF_OK')

asyncio.run(main())
