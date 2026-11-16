import asyncio, logging, sys
logging.disable(logging.INFO)
logging.getLogger().setLevel(logging.WARNING)

sys.path.insert(0, '.')
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    # lock probe: delete state file, observe -> expect locked notice; then write unlocked
    import os
    from pathlib import Path
    lock_file = Path('app/data/lock_state.json')
    if lock_file.exists():
        lock_file.unlink()
    notice = o._lock.observe('MOON love you 3000')
    print('LOCK_AFTER_DELETE=' + repr(notice)[:90])
    # tool registry: o._tools is a ToolManager; registry at o._tools._registry
    reg = o._tools._registry
    names = list(reg.tool_names)
    print('N_TOOLS=' + str(len(names)))
    print('HAVE_system_info=' + str('system_info' in names))
    r = await reg.get('system_info').execute()
    print('SYSTEM_INFO_OK=' + str('linux' in str(r)))
    # restore lock state so we never leave the system locked
    lock_file.parent.joinpath('lock_state.json').write_text('{"locked":false}\n')
    print('LOCK_STATE_RESTORED=false')
    await o.teardown()

asyncio.run(main())
