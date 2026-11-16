import asyncio
import sys

sys.path.insert(0, '.')
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator


async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    notice = o._lock.observe('MOON love you 3000')
    print('LOCK_NOTICE:', str(notice)[:90])
    res = await o._tools.run('system_info', {}, agent=None)
    txt = str(res)
    print('SYS_INFO_OK:', 'linux' in txt)
    print('HEAD:', txt[:120].replace(chr(10), ' '))
    await o.teardown()


asyncio.run(main())
