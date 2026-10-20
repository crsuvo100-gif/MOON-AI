import os
import sys

sys.path.insert(0, '.')

from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    # 1) unlock via the shared lock state file
    notice = o._lock.observe('MOON love you 3000')
    print('UNLOCK_NOTICE:', repr(notice))
    # 2) run the system_info tool for real
    res = await o._tools.run('system_info', {}, agent=None)
    txt = str(res.output) if res is not None else ''
    print('SYSTEM_INFO_LEN:', len(txt))
    print('SYSTEM_INFO_HEAD:', txt[:200].replace('\n', ' | '))
    ok = ('linux' in str(txt)) or ('Linux' in str(txt))
    print('LINUX_IN_OUTPUT:', ok)
    await o.teardown()
    sys.exit(0 if ok else 1)

import asyncio
asyncio.run(main())
