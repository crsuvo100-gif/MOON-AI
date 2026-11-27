import pytest

from moon.build import build_main


def test_build_verify_subcommand_has_project_arguments(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_main(["verify", "--help"])

    assert exc_info.value.code == 0
    assert "dir" in capsys.readouterr().out
