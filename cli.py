#!/usr/bin/env python3
"""MOON-AI Gateway CLI -- entry point.

Run with --gateway to start the ConnectionGateway: a persistent,
permission-gated connection registry that survives restarts.

    python cli.py --gateway

Press Ctrl+C to stop; the connection registry is saved atomically on
exit, so an interruption never leaves the on-disk state corrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import signal
import sys
from pathlib import Path

from app.connector.gateway import ConnectionGateway, ConnectionRecord
from app.connector.permission import ConnectorPermissionManager


def _make_build_all_parser() -> argparse.ArgumentParser:
    """Sub-parser for the moon build_all command."""
    p = argparse.ArgumentParser(prog="moon build_all",
                                description="Build and verify all MOON subsystems",
                                add_help=False)
    p.add_argument("goal", nargs="?", default="assemble all MOON subsystems",
                   help="human-readable goal for the build")
    p.add_argument("--status", action="store_true",
                   help="only report current status (skip acquisition)")
    p.add_argument("--json", metavar="FILE", default=None,
                   help="write build report as JSON to FILE")
    p.add_argument("--force", action="store_true",
                   help="re-verify all subsystems (skip discovery skip)")
    return p


def _cmd_build_all(args: argparse.Namespace) -> int:
    """Handler for the moon build_all command."""
    from app.brain.build_all import main as build_all_main

    saved_argv = sys.argv
    try:
        # Build sys.argv for build_all_main.
        # The build_all.py parser uses parse_args() with argv=None, which
        # consumes sys.argv[1:]. So we must NOT include the "build_all"
        # subcommand name (cli.py's subparser already consumed it).
        new_argv = ["moon"]  # prog name placeholder
        if args.goal:
            new_argv.append(args.goal)
        if args.status:
            new_argv.append("--status")
        if args.json:
            new_argv.extend(["--json", args.json])
        if args.force:
            new_argv.append("--force")
        sys.argv = new_argv
        return asyncio.run(build_all_main())
    finally:
        sys.argv = saved_argv


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="MOON-AI gateway entry point (persistent connection registry).",
    )
    parser.add_argument(
        "--gateway",
        action="store_true",
        help="start the ConnectionGateway interactive mode",
    )
    sub = parser.add_subparsers(dest="command", help="sub commands")

    u = sub.add_parser("register", help="register a new connection")
    u.add_argument("--name", required=True, help="connection name")
    u.add_argument("--kind", required=True,
                   help="service | agent | mcp | webhook | websocket")
    u.add_argument("--url", required=True, help="connection URL")
    u.add_argument("--model", default="", help="model name (agent connections)")
    u.add_argument("--scope", default="network.egress", help="permission scope")
    u.add_argument("--perm", action="append", default=[], help="permission scope")
    u.add_argument("--enabled/--disabled", default=True,
                   help="connection enabled state")

    # Build all sub-parser (no parents to avoid positional-arg conflicts on py3.14)
    bap = sub.add_parser("build_all", help="build and verify all MOON subsystems")
    bap.set_defaults(func=_cmd_build_all)
    bap.add_argument("goal", nargs="?", default="assemble all MOON subsystems",
                     help="human-readable goal for the build")
    bap.add_argument("--status", action="store_true",
                     help="only report current status (skip acquisition)")
    bap.add_argument("--json", metavar="FILE", default=None,
                     help="write build report as JSON to FILE")
    bap.add_argument("--force", action="store_true",
                     help="re-verify all subsystems (skip discovery skip)")

    return parser


def cmd_gateway() -> None:
    """Interactive gateway mode."""
    gw = ConnectionGateway()
    print(f"🌙 Gateway started (registry: {gw._file})")
    print(f"    {len(gw._conns)} connection(s) loaded")

    # Install Ctrl+C / SIGTERM handlers that save the registry atomically
    # before exiting, so restarts never see a half-written registry.json.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_sigint, sig, None, gw)

    from app.connector.connectors import AgentConnector

    while True:
        try:
            try:
                raw = input("gateway> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
        except (EOFError, KeyboardInterrupt):
            break

        if not raw:
            continue

        parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        try:
            if cmd in ("h", "help"):
                print('commands: register --name X --kind kind --url U [flags]')
                print('          list | remove NAME | status NAME | call NAME "msg" | quit')
                print('          exit')
            elif cmd in ("quit", "exit", "q"):
                print("  exiting gateway...")
                break
            elif cmd == "register":
                if len(args) < 3:
                    print("  usage: register --name X --kind kind --url U [--model M] [--scope S]")
                    continue
                name = args[0]
                kind = args[1].lower()
                url = args[2]
                rec = ConnectionRecord(
                    name=name,
                    kind=kind,
                    url=url,
                    model=args[3] if len(args) > 3 and args[3].isdigit() else "",
                    scope="network.egress",
                    permissions=("network.egress",),
                    enabled=True,
                )
                gw.register(rec)
                print(f"  registered {name}")

            elif cmd == "list":
                for rec in gw.list():
                    print(f"  {rec.name:<16} {rec.kind:<8} {rec.url}  ({rec.last_status})")

            elif cmd == "remove":
                if not args:
                    print("  usage: remove NAME")
                    continue
                if gw.remove(args[0]):
                    print(f"  removed {args[0]}")
                else:
                    print(f"  no such connection '{args[0]}'")

            elif cmd == "status":
                if not args:
                    print("  status NAME")
                    continue
                rec = gw.get(args[0])
                if rec:
                    print(f"  {args[0]}: {rec.last_status}  last_checked={rec.last_checked:.0f}")
                else:
                    print(f"  no such connection '{args[0]}'")

            elif cmd == "call":
                if len(args) < 2:
                    print('  usage: call NAME "message text"')
                    continue
                name = args[0]
                message = " ".join(args[1:])
                asyncio.run(gw.call_agent(name, message))
                print(f"  {name} done.")

            else:
                print(f"  unknown command '{cmd}'")

        except Exception as exc:  # noqa: BLE001
            print(f"  error: {exc}")


def _atomic_save(registry_path: Path, data: dict) -> None:
    """Write registry.json atomically: write to .tmp then rename."""
    tmp = registry_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(registry_path)


def _handle_sigint(sig, frame, gw: ConnectionGateway) -> None:
    """On Ctrl+C: save the registry atomically, then re-raise KeyboardInterrupt."""
    print("\n\n[gateway] cleaning up registry on interrupt...")
    try:
        gw._save()
        print(f"[gateway] registry saved to {gw._file}")
    except Exception as exc:  # noqa: BLE001
        print(f"[gateway] save error during shutdown: {exc}")
    raise KeyboardInterrupt


def main() -> None:
    parser = _make_parser()
    args = parser.parse_args()

    if args.gateway:
        cmd_gateway()
        return

    # Default: run MOON's normal CLI (same entry point as `moon` / `moon-terminal`).
    if hasattr(args, "func"):
        return args.func(args)

    from main import main as _run_moon

    _run_moon()


if __name__ == "__main__":
    main()
