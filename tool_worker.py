"""
Long-lived JSON-lines worker for FunctionGemma tool calls.

chat_ai.py keeps this process alive so tool_ai's model cache stays warm between
requests.
"""
import contextlib
import json
import sys


def _write(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def main() -> int:
    from tool_ai import run_task_for_backend

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        request_id = None
        try:
            request = json.loads(line)
            request_id = request.get("id")
            prompt = request.get("prompt") or ""
            with contextlib.redirect_stdout(sys.stderr):
                tool_call_raw, tool_result = run_task_for_backend(prompt)
            _write({"id": request_id, "tool_call_raw": tool_call_raw, "tool_result": tool_result})
        except Exception as exc:
            _write({"id": request_id, "error": str(exc), "tool_call_raw": None, "tool_result": None})

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
