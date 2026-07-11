# app/ops/docker_worker_smoke.py

"""Docker node worker 실행을 확인하는 smoke test script.

subprocess/docker 격리 모드가 기본 node payload를 정상 처리하는지 빠르게 검증한다.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from app.core.config import get_settings


def run_command(command: list[str], timeout: int = 120) -> tuple[int, str, str]:
    """run_command 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return completed.returncode, completed.stdout, completed.stderr
    except FileNotFoundError as exc:
        return 127, "", f"command not found: {command[0]} ({exc})"
    except Exception as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"


def ensure_image(image: str, build: bool) -> dict[str, object]:
    """ensure_image 함수. Docker node worker 실행을 확인하는 smoke test script. 입력을 검증/변환해 다음 단계가 사용할 값을 반환한다."""
    code, stdout, stderr = run_command(["docker", "image", "inspect", image], timeout=30)
    if code == 0:
        return {"name": "docker_image", "ok": True, "message": f"image exists: {image}"}
    if code == 127:
        return {"name": "docker_image", "ok": False, "message": "docker CLI not found. Install Docker Desktop or use GRAPH_NODE_EXECUTION_MODE=subprocess."}
    if not build:
        return {"name": "docker_image", "ok": False, "message": f"image not found: {image}. Run with --build-image or docker build -t {image} ."}

    build_code, build_stdout, build_stderr = run_command(["docker", "build", "-t", image, "."], timeout=600)
    return {
        "name": "docker_image_build",
        "ok": build_code == 0,
        "message": "image built" if build_code == 0 else f"build failed: {build_stderr or build_stdout}",
    }


def run_worker_probe(skip_vllm: bool) -> dict[str, object]:
    """run_worker_probe 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    settings = get_settings()
    repo_root = Path.cwd().resolve()
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--pids-limit",
        "256",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--env-file",
        str(repo_root / ".env"),
        "-v",
        f"{repo_root}:/app:rw",
        "-w",
        "/app",
        settings.graph_node_worker_image,
        "python",
        "-m",
        "app.ops.worker_probe",
    ]
    if skip_vllm:
        command.append("--skip-vllm")

    code, stdout, stderr = run_command(command, timeout=settings.graph_node_worker_timeout_seconds)
    if code != 0:
        return {"name": "docker_worker_probe", "ok": False, "message": stderr or stdout}
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"name": "docker_worker_probe", "ok": False, "message": f"invalid JSON: {stdout}"}
    return {"name": "docker_worker_probe", "ok": bool(payload.get("ok")), "message": payload, "raw": payload}


def run_smoke(build_image: bool = False, skip_vllm: bool = False) -> dict[str, object]:
    """run_smoke 함수. 외부 API, graph, worker, 평가 루틴 같은 실행 단위를 호출하고 결과를 반환한다."""
    settings = get_settings()
    checks = []

    docker_code, docker_stdout, docker_stderr = run_command(["docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
    checks.append({"name": "docker_daemon", "ok": docker_code == 0, "message": docker_stdout.strip() if docker_code == 0 else docker_stderr.strip()})
    if docker_code != 0:
        return {"ok": False, "checks": checks}

    image_check = ensure_image(settings.graph_node_worker_image, build=build_image)
    checks.append(image_check)
    if not image_check["ok"]:
        return {"ok": False, "checks": checks}

    checks.append(run_worker_probe(skip_vllm=skip_vllm))
    return {"ok": all(bool(item["ok"]) for item in checks), "checks": checks}


def parse_args() -> argparse.Namespace:
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-image", action="store_true")
    parser.add_argument("--skip-vllm", action="store_true")
    parser.add_argument("--strict", action="store_true")
    return parser.parse_args()


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    args = parse_args()
    result = run_smoke(build_image=args.build_image, skip_vllm=args.skip_vllm)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if args.strict and not result["ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
