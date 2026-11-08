import asyncio
import logging
import sys

logging.disable(logging.INFO)
logging.getLogger().setLevel(logging.ERROR)

sys.path.insert(0, '.')
from app.brain.orchestrator import Orchestrator
from app.config.settings import get_settings


async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    notice = o._lock.observe('MOON love you 3000')
    print('LOCK:', (notice[:60] if notice else '(already unlocked)'))
    res = await o._tools.run('system_info', {}, agent=None)
    # ToolManager embeds its own ToolResult (fields: name, output, success, error),
    # so check for the .output attribute rather than importing the base class.
    txt = res.output if hasattr(res, 'output') else (res or '')
    print('EXEC_OK:', 'linux' in txt.lower())
    print('OUT_LEN:', len(txt))
    print('OUT_HEAD:', txt[:120].replace(chr(10), ' | '))
    await o.teardown()


asyncio.run(main())
