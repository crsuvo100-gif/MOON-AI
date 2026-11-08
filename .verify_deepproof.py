import sys, asyncio, os
sys.path.insert(0, '.')
os.environ['HOME'] = '/home/meow'
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def go():
    o = Orchestrator(get_settings())
    await o.setup()
    try:
        notice = o._lock.observe('MOON love you 3000')
        print('UNLOCK_NOTICE=', (notice or '')[:120])
        res = await o._tools.run('system_info', {}, agent=None)
        print('SYSTEM_INFO_RESULT=', (res or '')[:400])
        assert 'linux' in (res or ''), 'linux not found in system_info output'
        print('RESULT=OK_deep_proof')
    finally:
        await o.teardown()

try:
    asyncio.run(go())
except Exception as e:
    print('RESULT=FAIL', type(e).__name__, e)
    sys.exit(1)
