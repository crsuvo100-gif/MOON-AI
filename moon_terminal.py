"""Compatibility shim for the legacy `python -m moon_terminal` entry point."""

from moon.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
