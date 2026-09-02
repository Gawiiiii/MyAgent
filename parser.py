import json
import re
import xml.etree.ElementTree as ET


def extract(text, tag):
    """提取无属性标签内容；参数为 str 原文和标签名，返回匹配内容 str 或 None。"""
    match = re.fullmatch(rf"\s*<{tag}>(.*?)</{tag}>\s*", text or "", re.DOTALL)
    return match.group(1) if match else None


def parse(raw):
    """解析模型工具/最终输出；参数为 str 原始响应，返回描述结果的 dict。"""
    if not raw or not raw.strip():
        return {"kind": "retry", "error": "empty response"}
    final = extract(raw, "final")
    if final is not None and final.strip():
        return {"kind": "final", "content": final}
    if final is not None:
        return {"kind": "retry", "error": "empty final response"}
    payload = extract(raw, "tool")
    if payload is None:
        # Accept the XML-style invoke envelope emitted by some models.  This
        # is normalized into the same internal tool-call representation as the
        # canonical JSON form.
        try:
            root = ET.fromstring(raw.strip())
            invoke = root.find("invoke") if root.tag == "tool" else None
            if invoke is not None and invoke.get("name") and len(root) == 1:
                args = {}
                for parameter in invoke.findall("parameter"):
                    parameter_name = parameter.get("name")
                    if not parameter_name or parameter_name in args or len(parameter):
                        raise ValueError("invalid invoke parameter")
                    args[parameter_name] = parameter.text or ""
                if len(args) == len(invoke):
                    return {"kind": "tool", "name": invoke.get("name"), "args": args}
        except (ET.ParseError, ValueError, TypeError):
            pass
        return {
            "kind": "retry",
            "error": (
                'expected exactly one <tool>{"name":"...","args":{...}}</tool> '
                'or <final>...</final> response'
            ),
        }
    try:
        call = json.loads(payload)
        if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("args", {}), dict):
            raise ValueError("tool call must contain a name and object args")
        return {"kind": "tool", "name": call["name"], "args": call.get("args", {})}
    except (json.JSONDecodeError, ValueError, TypeError) as exc:
        # The invoke form also uses a tool envelope, but its payload is XML;
        # recognize it after the canonical JSON parse fails.
        try:
            root = ET.fromstring(raw.strip())
            invoke = root.find("invoke") if root.tag == "tool" else None
            if invoke is not None and invoke.get("name") and len(root) == 1:
                args = {}
                for parameter in invoke.findall("parameter"):
                    parameter_name = parameter.get("name")
                    if not parameter_name or parameter_name in args or len(parameter):
                        raise ValueError("invalid invoke parameter")
                    args[parameter_name] = parameter.text or ""
                if len(args) == len(invoke):
                    return {"kind": "tool", "name": invoke.get("name"), "args": args}
        except (ET.ParseError, ValueError, TypeError):
            pass
        return {
            "kind": "retry",
            "error": (
                f"invalid tool JSON: {exc}; output exactly one "
                '<tool>{"name":"TOOL_NAME","args":{...}}</tool>'
            ),
        }
