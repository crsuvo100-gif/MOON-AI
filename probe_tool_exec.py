import asyncio
import sys

async def main() -> int:
    sys.path.insert(0, '.')

    from app.config.settings import get_settings
    from app.brain.orchestrator import Orchestrator

    # Build the orchestrator (same wiring as the web backend) and call setup()
    # to wire the tool registry + agents (real runtime, not a mock).
    settings = get_settings()
    o = Orchestrator(settings)
    await o.setup()

    # In-process unlock via the shared SessionLock (observed by the probe).
    notice = o._lock.observe('MOON love you 3000')
    print('LOCK_NOTICE:', notice)

    # Deep-proof: execute a REAL tool (system_info) in-process.
    res = await o._tools.run('system_info', {}, agent=None)
    out = res.output if hasattr(res, 'output') else str(res)
    print('TOOL_RESULT>', out[:400])
    assert isinstance(out, str) and 'linux' in out, repr(out)
    print('TOOL_EXEC_PROBE_OK')
    return 0

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
