import json
import re


def extract(text, tag):
    """提取无属性标签内容；参数为 str 原文和标签名，返回匹配内容 str 或 None。"""
    match = re.fullmatch(rf"\s*<{tag}>(.*?)</{tag}>\s*", text or "", re.DOTALL)
    return match.group(1) if match else None


def parse(raw):
    """解析模型工具/最终输出；参数为 str 原始响应，返回描述结果的 dict。"""
    if not raw or not raw.strip():
        return {"kind": "retry", "error": "empty response"}
    final = extract(raw, "final")
    if final is not None:
        return {"kind": "final", "content": final}
    payload = extract(raw, "tool")
    if payload is None:
        match = re.fullmatch(r'\s*<tool\s+name="(write_file|patch_file)"\s+path="([^"]+)">(.*?)</tool>\s*', raw or "", re.DOTALL)
        if match:
            name, file_path, body = match.groups()
            content_match = re.fullmatch(r"\s*<content>(.*?)</content>\s*", body, re.DOTALL)
            if name == "write_file" and content_match:
                return {"kind": "tool", "name": name, "args": {"path": file_path, "content": content_match.group(1)}}
            patch_match = re.fullmatch(r"\s*<old_text>(.*?)</old_text>\s*<new_text>(.*?)</new_text>\s*", body, re.DOTALL)
            if name == "patch_file" and patch_match:
                return {"kind": "tool", "name": name, "args": {"path": file_path, "old_text": patch_match.group(1), "new_text": patch_match.group(2)}}
    if payload is None:
        return {"kind": "retry", "error": "expected <tool>{JSON}</tool> or <final>...</final>"}
    try:
        call = json.loads(payload)
        if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("args", {}), dict):
            raise ValueError("tool call must contain a name and object args")
        return {"kind": "tool", "name": call["name"], "args": call.get("args", {})}
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        return {"kind": "retry", "error": f"invalid tool JSON: {exc}"}
