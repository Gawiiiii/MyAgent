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
    """格式化会话历史；参数为 dict 列表，返回历史文本 str。"""
    return "\n".join(f"[{item.get('role')}] {item.get('content', '')}" for item in history)


def build_prompt(agent, user_message):
    """组合完整模型 Prompt；参数为 MyAgent 和当前用户 str 消息，返回 Prompt str。"""
    return "\n\n".join([build_prefix(agent), agent.workspace.text(), "Memory:\n" + memory_text(agent.session), "History:\n" + history_text(agent.session["history"]), f"Current request: {user_message}"])
