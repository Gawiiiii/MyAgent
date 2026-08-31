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
    return "\n".join([
        "You are a coding agent. Work only with the workspace below.",
        "Available tools:", tools,
        'Respond with <tool>{"name":...,"args":{...}}</tool>, XML write/patch tags, or <final>answer</final>.',
    ])


def memory_text(session):
    """格式化工作记忆；参数为 dict 会话，返回记忆摘要 str。"""
    memory = session.get("memory", {})
    return f"task: {memory.get('task', '')}\nfiles: {', '.join(memory.get('files', []))}\nnotes: {'; '.join(memory.get('notes', []))}"


def history_text(history):
    """压缩并格式化会话历史；参数为 dict 列表，返回受限长度历史 str。"""
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
