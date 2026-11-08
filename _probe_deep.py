import sys, asyncio
sys.path.insert(0, ".")
from app.config.settings import get_settings
from app.brain.orchestrator import Orchestrator

async def main():
    o = Orchestrator(get_settings())
    await o.setup()
    n = o._lock.observe("MOON love you 3000")
    r = await o._tools.run("system_info", {}, agent=None)
    text = r.output if hasattr(r, "output") else r
    text = (text or "").lower()
    print("LOCK_NOTICE=" + str(n)[:60])
    print("SYSINFO_LEN=" + str(len(text or "")))
    print("HAS_LINUX=" + str("linux" in (text or "")))
    assert "linux" in (text or ""), "linux missing from system_info output"
    print("OK")

asyncio.run(main())
