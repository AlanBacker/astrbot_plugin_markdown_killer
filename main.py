from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import LLMResponse
from astrbot.api import logger
import re

@register("astrbot_plugin_markdown_killer", "Alan Backer", "移除LLM输出中的Markdown格式", "0.0.1", "https://github.com/AlanBacker/astrbot_plugin_markdown_killer")
class MarkdownKillerPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
    
    @filter.on_llm_response()
    async def on_llm_resp(self, event: AstrMessageEvent, resp: LLMResponse):
        """
        监听LLM回复，移除Markdown格式
        """
        if not resp or not resp.completion_text:
            return

        original_text = resp.completion_text
        
        cleaned_text = self.remove_markdown(original_text)
        
        if original_text != cleaned_text:
            resp.completion_text = cleaned_text
            # 使用 logger 提醒
            log_msg = f"[Markdown Killer] 检测到Markdown并移除: {original_text[:50].replace('\n', '\\n')}... -> {cleaned_text[:50].replace('\n', '\\n')}..."
            logger.info(log_msg)
            print(log_msg) # 强制输出到控制台以确保可见

    def remove_markdown(self, text: str) -> str:
        """
        移除文本中的Markdown格式
        """
        # 移除代码块 (保留内容)
        # 处理带有语言标识符的代码块
        text = re.sub(r"```.*?\n([\s\S]*?)```", r"\1", text, flags=re.MULTILINE)
        # 处理行内或没有换行的代码块
        text = re.sub(r"```(.*?)```", r"\1", text, flags=re.DOTALL)

        # 移除行内代码 `code` -> code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        
        # 移除粗体/斜体
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        text = re.sub(r"\*(?!\s)([^*]+)(?<!\s)\*", r"\1", text)
        text = re.sub(r"_(?!\s)([^_]+)(?<!\s)_", r"\1", text)
        
        # 移除标题 (移除 # 但保留文本)
        text = re.sub(r"^(#{1,6})\s+(.*)", r"\2", text, flags=re.MULTILINE)
        
        # 移除引用 (移除 > 但保留文本)
        text = re.sub(r"^>\s+(.*)", r"\1", text, flags=re.MULTILINE)
        
        # 移除链接 [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        
        # 移除列表标记 (移除行首的 - 或 *)
        text = re.sub(r"^\s*[-*]\s+(.*)", r"\1", text, flags=re.MULTILINE)
        
        return text
