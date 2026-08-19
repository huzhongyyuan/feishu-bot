"""Non-interactive Codex CLI adapter for scheduled publishing workflows."""
from __future__ import annotations

import fcntl
import os
import shutil
import subprocess
from pathlib import Path


class CodexAutomationError(RuntimeError):
    """Raised when the server Codex CLI cannot return a final answer."""


def _binary() -> str:
    configured = os.getenv("CODEX_AUTOMATION_BINARY", "").strip()
    if configured:
        return configured
    home_binary = Path.home() / ".local" / "bin" / "codex"
    if home_binary.is_file():
        return str(home_binary)
    return shutil.which("codex") or "codex"


def ask_codex(question: str, *, timeout: int | float = 300) -> str:
    """Run one isolated, read-only ``codex exec`` turn and return stdout."""
    question = str(question or "").strip()
    if not question:
        raise CodexAutomationError("Codex 自动化提示词为空。")

    reasoning = os.getenv("CODEX_AUTOMATION_REASONING", "medium").strip().lower()
    if reasoning not in {"minimal", "low", "medium", "high", "xhigh"}:
        raise CodexAutomationError("CODEX_AUTOMATION_REASONING 配置无效。")

    command = [
        _binary(),
        "exec",
        "--ephemeral",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-c",
        f'model_reasoning_effort="{reasoning}"',
        "-c",
        "mcp_servers.openaiDeveloperDocs.enabled=false",
    ]
    model = os.getenv("CODEX_AUTOMATION_MODEL", "").strip()
    if model:
        command.extend(("--model", model))
    command.append("-")

    workdir = Path(os.getenv("CODEX_AUTOMATION_CWD", "/tmp"))
    if not workdir.is_dir():
        raise CodexAutomationError(f"Codex 自动化工作目录不存在：{workdir}")

    lock_path = Path(
        os.getenv(
            "CODEX_AUTOMATION_LOCK_FILE",
            "/tmp/hzy-feishu-codex-automation.lock",
        )
    )
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise CodexAutomationError("Codex 自动化正在执行上一项任务。") from exc

        try:
            completed = subprocess.run(
                command,
                input=question,
                text=True,
                capture_output=True,
                cwd=str(workdir),
                timeout=max(30, int(timeout)),
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CodexAutomationError("Codex 自动化调用超时。") from exc
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    answer = completed.stdout.strip()
    if completed.returncode != 0:
        detail = completed.stderr.strip().splitlines()
        suffix = detail[-1] if detail else f"exit={completed.returncode}"
        raise CodexAutomationError(f"Codex 自动化调用失败：{suffix[:300]}")
    if not answer:
        raise CodexAutomationError("Codex 自动化没有返回最终答案。")
    return answer
