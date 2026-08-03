#!/usr/bin/env python3
"""MCP Server — NVIDIA NGC Cloud Management.

Wraps the NGC CLI to provide cloud management tools:
- Registry: models, images, resources, datasets
- Cloud Functions: create, deploy, manage
- Clusters & Tasks: monitor, logs, results
- GPU availability & diagnostics

Run via stdio transport. Qwen Code calls this as an MCP server.
"""

from __future__ import annotations

import json
import subprocess
import sys
from typing import Any

NGC_BIN = "/usr/local/bin/ngc"
DEFAULT_TIMEOUT = 30


def run_ngc(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    """Execute an NGC CLI command and return output."""
    cmd = [NGC_BIN] + args + ["--format_type", "json"]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            stderr = result.stderr.strip()
            return json.dumps({"error": stderr or output or f"Exit code {result.returncode}"})
        if not output:
            return json.dumps({"status": "ok", "message": "Command completed (no output)"})
        try:
            return json.dumps(json.loads(output))
        except json.JSONDecodeError:
            return output
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Command timed out after {timeout}s"})
    except FileNotFoundError:
        return json.dumps({"error": f"NGC CLI not found at {NGC_BIN}"})


def run_ngc_raw(args: list[str], timeout: int = DEFAULT_TIMEOUT) -> str:
    """Execute NGC CLI without forcing JSON output."""
    cmd = [NGC_BIN] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = result.stdout.strip()
        stderr = result.stderr.strip()
        if result.returncode != 0:
            return json.dumps({"error": stderr or output or f"Exit code {result.returncode}"})
        return output or json.dumps({"status": "ok"})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Command timed out after {timeout}s"})


TOOLS = [
    {
        "name": "ngc_model_list",
        "description": "List models in NGC registry. Supports filtering by org and collection.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "Organization name (optional, uses default)"},
            }
        }
    },
    {
        "name": "ngc_model_info",
        "description": "Get detailed info about a specific NGC model.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Model path (e.g. 'nvidia/llama-3.1-nemotron-70b-instruct')"},
            },
            "required": ["model"]
        }
    },
    {
        "name": "ngc_image_list",
        "description": "List container images in NGC registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "Organization name (optional)"},
            }
        }
    },
    {
        "name": "ngc_image_info",
        "description": "Get details about a specific container image.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "image": {"type": "string", "description": "Image path (e.g. 'nvidia/pytorch:24.07-py3')"},
            },
            "required": ["image"]
        }
    },
    {
        "name": "ngc_resource_list",
        "description": "List resources/datasets in NGC registry.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "org": {"type": "string", "description": "Organization name (optional)"},
            }
        }
    },
    {
        "name": "ngc_cf_function_list",
        "description": "List cloud functions (NIM endpoints, custom functions).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "ngc_cf_function_info",
        "description": "Get detailed info about a specific cloud function version.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "Function ID"},
                "version_id": {"type": "string", "description": "Version ID (optional)"},
            },
            "required": ["function_id"]
        }
    },
    {
        "name": "ngc_cf_function_create",
        "description": "Create a new cloud function. Returns the function ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Function name"},
                "inference_image": {"type": "string", "description": "Container image for inference"},
                "inference_model": {"type": "string", "description": "Model name/path"},
                "description": {"type": "string", "description": "Function description (optional)"},
            },
            "required": ["name"]
        }
    },
    {
        "name": "ngc_cf_function_deploy",
        "description": "Deploy a cloud function to a cluster.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "Function ID to deploy"},
                "version_id": {"type": "string", "description": "Version ID to deploy"},
                "cluster": {"type": "string", "description": "Target cluster name"},
                "gpu": {"type": "string", "description": "GPU type (e.g. 'A100', 'H100')"},
                "min_instances": {"type": "integer", "description": "Minimum instances (default 1)"},
                "max_instances": {"type": "integer", "description": "Maximum instances (default 1)"},
            },
            "required": ["function_id", "version_id"]
        }
    },
    {
        "name": "ngc_cf_cluster_list",
        "description": "List available NGC cloud function clusters.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "ngc_cf_available_gpus",
        "description": "List available GPU types for cloud function deployment.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "ngc_cf_task_list",
        "description": "List cloud function tasks/jobs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "function_id": {"type": "string", "description": "Filter by function ID (optional)"},
            }
        }
    },
    {
        "name": "ngc_cf_task_logs",
        "description": "Get logs for a specific cloud function task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "ngc_cf_task_results",
        "description": "Get results/output for a completed task.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
            },
            "required": ["task_id"]
        }
    },
    {
        "name": "ngc_registry_usage",
        "description": "Get NGC registry usage statistics (storage, downloads, etc).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "ngc_run",
        "description": "Run any NGC CLI command. Use for operations not covered by specific tools. Example: 'registry model list --org nvidia'",
        "inputSchema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "NGC CLI arguments as a string (e.g. 'registry model list --org nvidia')"},
            },
            "required": ["command"]
        }
    },
    {
        "name": "ngc_config",
        "description": "View current NGC CLI configuration (org, team, API key status).",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "ngc_diag",
        "description": "Run NGC diagnostics to check client configuration and connectivity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["client", "server", "all"], "description": "Diagnostic scope (default: client)"}
            }
        }
    },
]


def handle_tool_call(name: str, args: dict) -> str:
    """Route tool calls to NGC CLI commands."""

    if name == "ngc_model_list":
        cmd = ["registry", "model", "list"]
        if args.get("org"):
            cmd += ["--org", args["org"]]
        return run_ngc(cmd)

    elif name == "ngc_model_info":
        return run_ngc(["registry", "model", "info", args["model"]])

    elif name == "ngc_image_list":
        cmd = ["registry", "image", "list"]
        if args.get("org"):
            cmd += ["--org", args["org"]]
        return run_ngc(cmd)

    elif name == "ngc_image_info":
        return run_ngc(["registry", "image", "info", args["image"]])

    elif name == "ngc_resource_list":
        cmd = ["registry", "resource", "list"]
        if args.get("org"):
            cmd += ["--org", args["org"]]
        return run_ngc(cmd)

    elif name == "ngc_cf_function_list":
        return run_ngc(["cloud-function", "function", "list"])

    elif name == "ngc_cf_function_info":
        cmd = ["cloud-function", "function", "info", args["function_id"]]
        if args.get("version_id"):
            cmd += ["--version", args["version_id"]]
        return run_ngc(cmd)

    elif name == "ngc_cf_function_create":
        cmd = ["cloud-function", "function", "create", "--name", args["name"]]
        if args.get("inference_image"):
            cmd += ["--inference-image", args["inference_image"]]
        if args.get("inference_model"):
            cmd += ["--inference-model", args["inference_model"]]
        if args.get("description"):
            cmd += ["--description", args["description"]]
        return run_ngc(cmd, timeout=60)

    elif name == "ngc_cf_function_deploy":
        cmd = ["cloud-function", "function", "deploy",
               args["function_id"], args["version_id"]]
        if args.get("cluster"):
            cmd += ["--cluster", args["cluster"]]
        if args.get("gpu"):
            cmd += ["--gpu", args["gpu"]]
        if args.get("min_instances"):
            cmd += ["--min-instances", str(args["min_instances"])]
        if args.get("max_instances"):
            cmd += ["--max-instances", str(args["max_instances"])]
        return run_ngc(cmd, timeout=60)

    elif name == "ngc_cf_cluster_list":
        return run_ngc(["cloud-function", "cluster", "list"])

    elif name == "ngc_cf_available_gpus":
        return run_ngc(["cloud-function", "available-gpus"])

    elif name == "ngc_cf_task_list":
        cmd = ["cloud-function", "task", "list"]
        if args.get("function_id"):
            cmd += ["--function-id", args["function_id"]]
        return run_ngc(cmd)

    elif name == "ngc_cf_task_logs":
        return run_ngc(["cloud-function", "task", "logs", args["task_id"]], timeout=45)

    elif name == "ngc_cf_task_results":
        return run_ngc(["cloud-function", "task", "results", args["task_id"]], timeout=45)

    elif name == "ngc_registry_usage":
        return run_ngc(["registry", "usage"])

    elif name == "ngc_run":
        parts = args["command"].split()
        return run_ngc_raw(parts, timeout=60)

    elif name == "ngc_config":
        return run_ngc_raw(["config", "current"])

    elif name == "ngc_diag":
        scope = args.get("scope", "client")
        return run_ngc_raw(["diag", scope])

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})


def handle_request(request: dict) -> dict:
    """Handle a JSON-RPC request."""
    method = request.get("method", "")
    req_id = request.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "nvidia-ngc-mcp",
                    "version": "1.0.0"
                }
            }
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": TOOLS}
        }

    if method == "tools/call":
        tool_name = request.get("params", {}).get("name", "")
        args = request.get("params", {}).get("arguments", {})

        try:
            result = handle_tool_call(tool_name, args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": result}]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)}
            }

    if method == "notifications/initialized":
        return {"jsonrpc": "2.0"}

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def main():
    """Run MCP server over stdio."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except json.JSONDecodeError:
            continue
        except Exception as e:
            error_resp = {
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": str(e)}
            }
            sys.stdout.write(json.dumps(error_resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
