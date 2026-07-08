# app/agents/sandbox.py

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings

ALLOWED_COMMAND_BASENAMES = {
    "python",
    "python3",
    "python3.10",
    "python3.11",
    "python3.12",
    "pytest",
}

DENIED_COMMAND_BASENAMES = {
    "bash",
    "sh",
    "zsh",
    "fish",
    "curl",
    "wget",
    "ssh",
    "scp",
    "nc",
    "netcat",
    "telnet",
    "docker",
    "kubectl",
    "rm",
    "mv",
    "chmod",
    "chown",
    "sudo",
}

DENIED_ARGUMENT_TOKENS = {
    "--privileged",
    "--network=host",
    "--cap-add",
    "--volume",
    "-v",
    "--mount",
}


class AgentSandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class SandboxResult:
    mode: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "timed_out": self.timed_out,
        }


def command_basename(command: str) -> str:
    return Path(command).name.lower()


def validate_command_safety(command: list[str]) -> None:
    if not command:
        raise AgentSandboxError("Sandbox command cannot be empty.")

    executable = command_basename(command[0])
    if executable in DENIED_COMMAND_BASENAMES:
        raise AgentSandboxError(f"Denied sandbox executable: {executable}")
    if executable not in ALLOWED_COMMAND_BASENAMES:
        raise AgentSandboxError(
            f"Executable '{executable}' is not in the sandbox allowlist. "
            f"Allowed: {sorted(ALLOWED_COMMAND_BASENAMES)}"
        )

    for arg in command[1:]:
        normalized = str(arg).strip().lower()
        if normalized in DENIED_ARGUMENT_TOKENS:
            raise AgentSandboxError(f"Denied sandbox argument: {arg}")
        if normalized.startswith(("--network=", "--cap-add=", "--mount=")):
            raise AgentSandboxError(f"Denied sandbox argument: {arg}")


def run_direct_command(command: list[str], timeout_seconds: int) -> SandboxResult:
    validate_command_safety(command)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        return SandboxResult(mode="direct", returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
    except subprocess.TimeoutExpired as exc:
        return SandboxResult(mode="direct", returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "timeout", timed_out=True)


def run_docker_command(command: list[str], timeout_seconds: int) -> SandboxResult:
    validate_command_safety(command)
    settings = get_settings()
    with tempfile.TemporaryDirectory(prefix="ax-agent-sandbox-") as temp_dir:
        payload_path = Path(temp_dir) / "command.json"
        payload_path.write_text(json.dumps({"command": command}, ensure_ascii=False), encoding="utf-8")
        docker_command = [
            "docker",
            "run",
            "--rm",
            "--network",
            settings.agent_tool_sandbox_network,
            "--cpus",
            "1",
            "--memory",
            "512m",
            "--pids-limit",
            "128",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "-v",
            f"{temp_dir}:/sandbox:ro",
            settings.agent_tool_sandbox_image,
            *command,
        ]
        try:
            completed = subprocess.run(docker_command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            return SandboxResult(mode="docker", returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(mode="docker", returncode=124, stdout=exc.stdout or "", stderr=exc.stderr or "timeout", timed_out=True)


def run_sandboxed_command(command: list[str], timeout_seconds: int | None = None) -> SandboxResult:
    settings = get_settings()
    timeout = timeout_seconds or settings.agent_tool_sandbox_timeout_seconds
    mode = settings.agent_tool_sandbox_mode.lower()

    if mode == "direct":
        return run_direct_command(command=command, timeout_seconds=timeout)
    if mode == "docker":
        return run_docker_command(command=command, timeout_seconds=timeout)
    raise AgentSandboxError(f"Unsupported AGENT_TOOL_SANDBOX_MODE: {settings.agent_tool_sandbox_mode}")


def assert_sandbox_available() -> None:
    settings = get_settings()
    if settings.agent_tool_sandbox_mode.lower() != "docker":
        return
    result = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, text=True, timeout=5, check=False)
    if result.returncode != 0:
        raise AgentSandboxError(f"Docker sandbox mode is enabled but Docker is unavailable: {result.stderr}")
