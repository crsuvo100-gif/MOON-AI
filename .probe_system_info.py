import asyncio, sys
sys.path.insert(0, ".")
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    o._lock.observe("MOON love you 3000")
    res = None
    try:
        res = await o._tools.run("system_info", {}, agent=None)
    except Exception as e:
        print("RUN_FAIL", type(e).__name__, e)
    if res is None:
        t = o._tools._registry.get("system_info")
        if t is not None:
            res = await t.execute()
    txt = str(res)
    lowered = txt.lower()
    print("TOOL_OK" if ("linux" in lowered or "linux 7" in lowered) else "TOOL_BAD")
    print("LEN", len(txt))
    print("FIRST", txt[:120].replace("\n", " "))
    await o.teardown()

asyncio.run(main())
