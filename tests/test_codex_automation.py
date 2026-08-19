import subprocess

import codex_automation


def test_ask_codex_uses_ephemeral_read_only_exec(monkeypatch, tmp_path):
    captured = {}

    def fake_run(command, **kwargs):
        captured.update({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout='{"ok":true}\n', stderr="")

    monkeypatch.setenv("CODEX_AUTOMATION_BINARY", "/opt/codex")
    monkeypatch.setenv("CODEX_AUTOMATION_CWD", str(tmp_path))
    monkeypatch.setenv("CODEX_AUTOMATION_LOCK_FILE", str(tmp_path / "lock"))
    monkeypatch.setenv("CODEX_AUTOMATION_REASONING", "low")
    monkeypatch.setattr(codex_automation.subprocess, "run", fake_run)

    assert codex_automation.ask_codex("strict json", timeout=90) == '{"ok":true}'
    assert captured["command"][0] == "/opt/codex"
    assert "--ephemeral" in captured["command"]
    assert ["--sandbox", "read-only"] == captured["command"][3:5]
    assert captured["command"][-1] == "-"
    assert captured["input"] == "strict json"
    assert captured["timeout"] == 90


def test_ask_codex_surfaces_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("CODEX_AUTOMATION_CWD", str(tmp_path))
    monkeypatch.setenv("CODEX_AUTOMATION_LOCK_FILE", str(tmp_path / "lock"))
    monkeypatch.setattr(
        codex_automation.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, stdout="", stderr="provider unavailable"
        ),
    )

    try:
        codex_automation.ask_codex("hello")
    except codex_automation.CodexAutomationError as exc:
        assert "provider unavailable" in str(exc)
    else:
        raise AssertionError("expected CodexAutomationError")
