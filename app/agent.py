import base64
from datetime import date
from pathlib import Path

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_openai import ChatOpenAI

from .config import settings


PROMPT_PATH = Path(__file__).with_name('prompts') / 'chat_system.txt'


def load_system_prompt():
    """Read on each request so prompt edits take effect on the next message."""
    return PROMPT_PATH.read_text(encoding='utf-8').strip()


def chat_model():
    if not settings.chat_api_key:
        raise RuntimeError('尚未配置 DEEPSEEK_API_KEY')
    return ChatOpenAI(
        model=settings.chat_model,
        api_key=settings.chat_api_key,
        base_url=settings.chat_base_url,
        temperature=0.2,
        extra_body={'thinking':{'type':'disabled'}},
    )


def _message_content(message, attachments):
    text = message["content"] or "请分析我上传的材料。"
    if not attachments:
        return text
    parts = [{"type": "text", "text": text}]
    for item in attachments:
        if item["mime_type"].startswith("image/"):
            encoded = base64.b64encode(item["body"]).decode("ascii")
            parts.append({"type": "image_url", "image_url": {"url": f"data:{item['mime_type']};base64,{encoded}"}})
        elif item.get("extracted_text"):
            parts.append({"type": "text", "text": f"上传文件《{item['filename']}》节选：\n{item['extracted_text'][:16000]}"})
    return parts


def answer(conversation, attachment_rows):

    @tool
    def search_uploaded_files(keyword: str) -> str:
        """在当前会话用户上传的文档文本中查找关键词，返回相关原文及文件名。"""
        matches = []
        needle = keyword.casefold().strip()
        if not needle:
            return "请提供关键词。"
        for item in attachment_rows:
            source = item.get("extracted_text") or ""
            pos = source.casefold().find(needle)
            if pos >= 0:
                matches.append(f"《{item['filename']}》：{source[max(0,pos-250):pos+700]}")
        return "\n\n".join(matches[:8]) or "当前会话的已上传文档中未找到该关键词。"

    @tool
    def current_date() -> str:
        """获取当前本地日期，用于判断时间相关问题。"""
        return date.today().isoformat()

    model = chat_model()
    prompt = load_system_prompt()
    agent = create_agent(model=model, tools=[search_uploaded_files, current_date], system_prompt=prompt)
    messages = []
    for item in conversation["messages"][-30:]:
        if item["role"] == "user":
            files = [row for row in attachment_rows if row.get("message_id") == item["id"]]
            messages.append({"role": "user", "content": _message_content(item, files)})
        else:
            messages.append({"role": "assistant", "content": item["content"]})
    result = agent.invoke({"messages": messages})
    content = result["messages"][-1].content
    if isinstance(content, list):
        content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict))
    return str(content).strip() or "模型没有返回文本，请重试。"
