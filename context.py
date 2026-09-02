MAX_HISTORY = 12000


def clip(text, limit=4000):
    """截断过长文本；参数为任意文本和 int 字符上限，返回不超过上限的 str。"""
    text = str(text)
    if len(text) <= limit:
        return text
    marker = f"\n...[truncated {len(text) - limit} chars]"
    return text[: max(0, limit - len(marker))] + marker[:limit]


def middle(text, limit):
    """保留文本首尾内容；参数为文本 str 和 int 上限，返回压缩后的 str。"""
    """用于在对话历史中对较早的工具输出进行压缩，保留首尾内容以节省历史长度。"""
    text = str(text)
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    left = (limit - 3) // 2
    return text[:left] + "..." + text[-(limit - 3 - left):]


def build_prefix(agent):
    """构造固定系统提示；参数为 MyAgent，返回稳定前缀 str。"""
    tools = "\n".join(f"- {name}: {item['description']} (args: {item['schema']})" for name, item in agent.tools.items())
    rules = [
        "You are a coding agent. Work only with the workspace below.",
        "Available tools:", tools,
        "You must output exactly one message, and it must use one of these two forms only:\n"
        'Tool call: <tool>{"name":"read_file","args":{"path":"README.md"}}</tool>\n'
        "Final answer: <final>Task completed.</final>\n"
        "Strict output rules:\n"
        "1. The response must start with <tool> or <final> and end with the matching closing tag.\n"
        "2. Output exactly one tag; never emit multiple tool calls.\n"
        "3. Do not output Markdown, code fences, explanations, planning text, or any prefix/suffix.\n"
        "4. For compatibility, a tool call may alternatively use exactly one XML invoke envelope: "
        '<tool><invoke name="read_file"><parameter name="path">README.md</parameter></invoke></tool>. '
        "Do not use any other XML shape.\n"
        "5. A tool call must contain valid JSON with a string name and an object args field.\n"
        "6. For write_file, put the complete file text in the JSON args.content string.\n"
        "7. For patch_file, put the exact replacement fields in JSON args.old_text and args.new_text.\n"
        "8. When a tool is needed, emit the tool tag immediately; do not describe the intended action first.",
        "For read_file, use retry=true only when retrying the same read after that read failed. After a successful read, file change, or command, read normally without retry.",
    ]
    if agent.read_only:
        rules.insert(1, "You are a read-only delegated agent. Only inspect files; never write or run commands.")
    return "\n".join(rules)


def memory_text(session):
    """格式化工作记忆；参数为 dict 会话，返回记忆摘要 str。"""
    memory = session.get("memory", {})
    return f"task: {memory.get('task', '')}\nfiles: {', '.join(memory.get('files', []))}\nnotes: {'; '.join(memory.get('notes', []))}"


def history_text(history):
    """压缩并格式化会话历史；参数为 dict 列表，返回受限长度历史 str。"""
    """最近的六条记录完整保存，更早的工具调用历史会用middle()压缩到500字符以内，连续的重复读取文件操作会被省略，但是写入/修改文件操作会重置连续读取的省略逻辑。"""
    rendered, previous_read = [], None
    recent_start = max(0, len(history) - 6)
    for index, item in enumerate(history):
        name, args = item.get("name"), item.get("args", {})
        if item.get("role") == "tool" and name == "read_file":
            current_read = args.get("path") if isinstance(args, dict) else None
            if current_read and current_read == previous_read:
                continue
            previous_read = current_read
        elif item.get("role") == "tool" and name in {"write_file", "patch_file"}:
            previous_read = None
        content = item.get("content", "")
        if index < recent_start and item.get("role") == "tool":
            content = middle(content, 500)
        rendered.append(f"[{item.get('role')}] {content}")
    return clip("\n".join(rendered), MAX_HISTORY)


def build_prompt(agent, user_message):
    """组合完整模型 Prompt；参数为 MyAgent 和当前用户 str 消息，返回 Prompt str。"""
    return "\n\n".join([build_prefix(agent), agent.workspace.text(), "Memory:\n" + memory_text(agent.session), "History:\n" + history_text(agent.session["history"]), f"Current request: {user_message}"])
