# app/graph/node_worker.py

"""graph node를 direct/subprocess/docker 방식으로 실행하는 wrapper.

노드 격리와 timeout, 실행 모드 trace를 제공해 긴 작업이 전체 프로세스를 망가뜨리지
않게 한다.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.graph.state import AXPlannerState
from app.monitoring.metrics import record_agent_node

NODE_TARGETS = {
    "load_project_data": "app.graph.nodes:load_project_data_node",
    "retrieve_context": "app.graph.nodes:retrieve_context_node",
    "process_analyzer": "app.graph.analysis_nodes:process_analyzer_node",
    "data_readiness": "app.graph.analysis_nodes:data_readiness_node",
    "automation_feasibility": "app.graph.analysis_nodes:automation_feasibility_node",
    "roi_cost": "app.graph.analysis_nodes:roi_cost_node",
    "risk_governance": "app.graph.analysis_nodes:risk_governance_node",
    "compliance_assessment": "app.graph.compliance_node:compliance_assessment_node",
    "priority_ranking": "app.graph.analysis_nodes:priority_ranking_node",
    "agent_evaluator": "app.graph.agent_evaluator_node:agent_evaluator_node",
    "llm_critic": "app.graph.llm_critic_node:llm_critic_node",
    "agent_replan": "app.graph.replan_node:agent_replan_node",
    "human_review": "app.graph.review_node:human_review_node",
    "poc_delivery_planner": "app.graph.poc_node:poc_delivery_planner_node",
    "report_writer": "app.graph.nodes:report_writer_node",
    "docx_generator": "app.graph.nodes:docx_generator_node",
}

# LangGraph interrupt()는 runnable/checkpointer context 안에서만 동작한다.
# subprocess/docker worker에서는 langgraph.config.get_config() context가 없어 실패하므로
# Human Review node는 항상 parent graph process에서 직접 실행한다.
NON_WORKERIZABLE_NODES = {"human_review"}


class NodeWorkerError(RuntimeError):
    """격리 node worker 실행 중 발생한 오류를 호출자에게 전달하는 예외다."""
    pass


def import_node(node_name: str) -> Callable[[AXPlannerState], dict[str, Any]]:
    """NODE_TARGETS의 "module:function" 문자열을 실제 graph 실행 callable로 import한다."""
    target = NODE_TARGETS.get(node_name)
    if not target:
        raise NodeWorkerError(f"Unknown graph node: {node_name}")
    module_name, function_name = target.split(":", 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, function_name)
    return fn


def run_node_direct(node_name: str, state: AXPlannerState) -> dict[str, Any]:
    """현재 프로세스에서 node 함수를 바로 실행한다."""
    return import_node(node_name)(state)


def run_node_subprocess(node_name: str, state: AXPlannerState, timeout_seconds: int) -> dict[str, Any]:
    """state를 임시 JSON으로 넘겨 별도 Python subprocess에서 node를 실행한다."""
    with tempfile.TemporaryDirectory(prefix="ax-node-worker-") as temp_dir:
        state_path = Path(temp_dir) / "state.json"
        output_path = Path(temp_dir) / "output.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")

        env = dict(os.environ)
        env["GRAPH_NODE_EXECUTION_MODE"] = "direct"
        command = [
            sys.executable,
            "-m",
            "app.graph.node_worker",
            "--node",
            node_name,
            "--state-file",
            str(state_path),
            "--output-file",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False, env=env)
        if completed.returncode != 0:
            raise NodeWorkerError(
                f"Node worker failed for {node_name}: returncode={completed.returncode}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )
        if not output_path.exists():
            raise NodeWorkerError(f"Node worker did not write output for {node_name}.")
        return json.loads(output_path.read_text(encoding="utf-8"))


def run_node_docker(node_name: str, state: AXPlannerState, timeout_seconds: int) -> dict[str, Any]:
    """Docker sandbox 안에서 node를 실행해 timeout/메모리/권한 경계를 더 강하게 둔다."""
    settings = get_settings()
    repo_root = Path.cwd().resolve()
    with tempfile.TemporaryDirectory(prefix="ax-node-worker-") as temp_dir:
        state_path = Path(temp_dir) / "state.json"
        output_path = Path(temp_dir) / "output.json"
        state_path.write_text(json.dumps(state, ensure_ascii=False, default=str), encoding="utf-8")
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
            "-e",
            "GRAPH_NODE_EXECUTION_MODE=direct",
            "--env-file",
            str(repo_root / ".env"),
            "-v",
            f"{repo_root}:/app:rw",
            "-v",
            f"{temp_dir}:/worker:rw",
            "-w",
            "/app",
            settings.graph_node_worker_image,
            "python",
            "-m",
            "app.graph.node_worker",
            "--node",
            node_name,
            "--state-file",
            "/worker/state.json",
            "--output-file",
            "/worker/output.json",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout_seconds, check=False)
        if completed.returncode != 0:
            raise NodeWorkerError(
                f"Docker node worker failed for {node_name}: returncode={completed.returncode}\n"
                f"stdout={completed.stdout}\nstderr={completed.stderr}"
            )
        if not output_path.exists():
            raise NodeWorkerError(f"Docker node worker did not write output for {node_name}.")
        return json.loads(output_path.read_text(encoding="utf-8"))


def run_node_via_worker(node_name: str, state: AXPlannerState) -> dict[str, Any]:
    """설정값에 따라 direct/subprocess/docker 실행 경로 중 하나를 선택한다."""
    if node_name in NON_WORKERIZABLE_NODES:
        return run_node_direct(node_name, state)

    settings = get_settings()
    mode = settings.graph_node_execution_mode.lower()
    if mode == "direct":
        return run_node_direct(node_name, state)
    if mode == "subprocess":
        return run_node_subprocess(node_name, state, timeout_seconds=settings.graph_node_worker_timeout_seconds)
    if mode == "docker":
        return run_node_docker(node_name, state, timeout_seconds=settings.graph_node_worker_timeout_seconds)
    raise NodeWorkerError(f"Unsupported GRAPH_NODE_EXECUTION_MODE: {settings.graph_node_execution_mode}")


def workerized_node(node_name: str) -> Callable[[AXPlannerState], dict[str, Any]]:
    """LangGraph에 등록할 수 있도록 node 실행 함수에 worker 선택과 metric 기록을 감싼다."""
    def _node(state: AXPlannerState) -> dict[str, Any]:
        """실제 graph tick에서 호출되는 wrapper로, 성공/실패 latency metric을 남긴다."""
        settings = get_settings()
        mode = "direct" if node_name in NON_WORKERIZABLE_NODES else settings.graph_node_execution_mode.lower()
        start = time.perf_counter()
        status = "success"
        try:
            return run_node_via_worker(node_name, state)
        except Exception:
            status = "failed"
            raise
        finally:
            record_agent_node(node_name=node_name, mode=mode, status=status, latency_seconds=time.perf_counter() - start)

    _node.__name__ = f"workerized_{node_name}"
    return _node


def parse_args() -> argparse.Namespace:
    """CLI 실행 인자를 정의하고 argparse Namespace로 변환한다."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--output-file", required=True)
    return parser.parse_args()


def main() -> None:
    """해당 모듈을 script로 실행했을 때 호출되는 진입점이다."""
    args = parse_args()
    state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    result = run_node_direct(args.node, state)
    Path(args.output_file).write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
