import sys, os, asyncio

# sanitize env (host quirk: Hermes PYTHONPATH poisons .venv)
for k in list(os.environ):
    if k in ('PYTHONPATH', 'VIRTUAL_ENV', 'PYTHONHOME'):
        os.environ.pop(k, None)

sys.path.insert(0, '.')

from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()

    # unlock with the terminal phrase (shared lock_state.json)
    notice = o._lock.observe('MOON love you 3000')
    print('LOCK_NOTICE:', (notice or 'NONE')[:90])

    # deep-proof agent -> tool execution path
    try:
        res = await o._tools.run('system_info', {}, agent=None)
    except Exception as e:
        res = f'<EXCEPTION {type(e).__name__}: {e}>'
    text = res if isinstance(res, str) else str(res)
    print('SYSTEM_INFO_BYTES:', len(text))
    print('LINUX_IN_OUTPUT:', ('linux' in text.lower()))
    print('RESULT_PREVIEW:', text[:260])

    await o.teardown()

asyncio.run(main())
