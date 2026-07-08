# app/graph/node_worker.py

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.graph.state import AXPlannerState

NODE_TARGETS = {
    "load_project_data": "app.graph.nodes:load_project_data_node",
    "retrieve_context": "app.graph.nodes:retrieve_context_node",
    "process_analyzer": "app.graph.nodes:process_analyzer_node",
    "data_readiness": "app.graph.nodes:data_readiness_node",
    "automation_feasibility": "app.graph.nodes:automation_feasibility_node",
    "roi_cost": "app.graph.nodes:roi_cost_node",
    "risk_governance": "app.graph.nodes:risk_governance_node",
    "compliance_assessment": "app.graph.compliance_node:compliance_assessment_node",
    "priority_ranking": "app.graph.nodes:priority_ranking_node",
    "agent_evaluator": "app.graph.agent_evaluator_node:agent_evaluator_node",
    "llm_critic": "app.graph.llm_critic_node:llm_critic_node",
    "agent_replan": "app.graph.replan_node:agent_replan_node",
    "human_review": "app.graph.review_node:human_review_node",
    "poc_delivery_planner": "app.graph.poc_node:poc_delivery_planner_node",
    "report_writer": "app.graph.nodes:report_writer_node",
    "docx_generator": "app.graph.nodes:docx_generator_node",
}

# LangGraph interrupt() requires runnable/checkpointer context. If this node is
# executed in a subprocess or Docker worker, langgraph.config.get_config() is not
# available and interrupt() fails. Keep it in the parent graph process.
NON_WORKERIZABLE_NODES = {"human_review"}


class NodeWorkerError(RuntimeError):
    pass


def import_node(node_name: str) -> Callable[[AXPlannerState], dict[str, Any]]:
    target = NODE_TARGETS.get(node_name)
    if not target:
        raise NodeWorkerError(f"Unknown graph node: {node_name}")
    module_name, function_name = target.split(":", 1)
    module = importlib.import_module(module_name)
    fn = getattr(module, function_name)
    return fn


def run_node_direct(node_name: str, state: AXPlannerState) -> dict[str, Any]:
    return import_node(node_name)(state)


def run_node_subprocess(node_name: str, state: AXPlannerState, timeout_seconds: int) -> dict[str, Any]:
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
    def _node(state: AXPlannerState) -> dict[str, Any]:
        return run_node_via_worker(node_name, state)

    _node.__name__ = f"workerized_{node_name}"
    return _node


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--node", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--output-file", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    result = run_node_direct(args.node, state)
    Path(args.output_file).write_text(json.dumps(result, ensure_ascii=False, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
