# tests/

Test suite for MOON-AI:

- **unit/** — fast unit tests (10 tests, run via `pytest tests/unit`)
- **integration/** — integration tests (require live LLM, timeout in full suite)

Run fast subset: `pytest tests/unit -q`
Run full suite: `make test` (times out at 300s due to live LLM integration tests)
