import json
import re


def extract(text, tag):
    match = re.fullmatch(rf"\s*<{tag}>(.*?)</{tag}>\s*", text or "", re.DOTALL)
    return match.group(1) if match else None


def parse(raw):
    if not raw or not raw.strip():
        return {"kind": "retry", "error": "empty response"}
    final = extract(raw, "final")
    if final is not None:
        return {"kind": "final", "content": final}
    payload = extract(raw, "tool")
    if payload is None:
        return {"kind": "retry", "error": "expected <tool>{JSON}</tool> or <final>...</final>"}
    try:
        call = json.loads(payload)
        if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("args", {}), dict):
            raise ValueError("tool call must contain a name and object args")
        return {"kind": "tool", "name": call["name"], "args": call.get("args", {})}
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return {"kind": "retry", "error": f"invalid tool JSON: {exc}"}
