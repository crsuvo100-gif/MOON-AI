import asyncio, logging
logging.disable(logging.INFO)
logging.getLogger().setLevel(logging.WARNING)

from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    notice = o._lock.observe('MOON love you 3000')
    res = await o._tools.run('system_info', {}, agent=None)
    tools = list(o._tools._registry.tool_names)
    print('UNLOCK_NOTICE=' + str(notice)[:80])
    print('SYSTEM_INFO_OK=' + str('linux' in (res or '')))
    print('N_AGENTS=' + str(len(o._agents)))
    print('N_TOOLS=' + str(len(tools)))
    print('TOOLS=' + ','.join(sorted(tools)))
    await o.teardown()

asyncio.run(main())
