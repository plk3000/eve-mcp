from __future__ import annotations

from pathlib import Path


def test_project_is_standalone_and_defaults_to_stdio() -> None:
    root = Path(__file__).parents[1]
    pyproject = (root / "pyproject.toml").read_text()
    assert "eve-mining-support" not in pyproject

    from eve_mcp.config import Settings

    settings = Settings()
    assert settings.transport == "stdio"
    assert settings.http_host == "127.0.0.1"


def test_cli_help_needs_no_credentials() -> None:
    from typer.testing import CliRunner

    from eve_mcp.cli import app

    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.stdout


def test_production_code_has_no_game_automation_imports() -> None:
    root = Path(__file__).parents[1] / "src"
    forbidden = ("pyautogui", "pynput", "easyocr", "pytesseract", "mss", "xdotool", "wmctrl")
    text = "\n".join(path.read_text() for path in root.rglob("*.py"))
    assert not any(item in text for item in forbidden)
