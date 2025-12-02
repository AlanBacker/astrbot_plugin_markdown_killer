from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import LLMResponse
from astrbot.api import logger
import re

@register("astrbot_plugin_markdown_killer", "AlanBacker", "移除LLM输出中的Markdown格式", "0.0.2", "https://github.com/AlanBacker/astrbot_plugin_markdown_killer")
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
        
        # 调试日志：显示收到的原始文本，以便确认 LLM 是否输出了 Markdown
        original_preview_debug = original_text[:50].replace('\n', '\\n')
        logger.info(f"[Markdown Killer] 收到 LLM 回复 (前50字符): {original_preview_debug}...")
        
        cleaned_text = self.remove_markdown(original_text)
        
        if original_text != cleaned_text:
            resp.completion_text = cleaned_text
            # 使用 logger 提醒
            original_preview = original_text[:50].replace('\n', '\\n')
            cleaned_preview = cleaned_text[:50].replace('\n', '\\n')
            log_msg = f"\n[Markdown Killer] --------------------------------------------------\n[Markdown Killer] 检测到Markdown并移除:\n[Markdown Killer] 原文: {original_preview}...\n[Markdown Killer] 处理: {cleaned_preview}...\n[Markdown Killer] --------------------------------------------------"
            logger.warning(log_msg)

    def remove_markdown(self, text: str) -> str:
        """
        移除文本中的Markdown格式
        """
        # 移除代码块 (保留内容)
        # 合并处理: 使用 DOTALL 模式匹配 ```...```，非贪婪匹配
        # 尝试移除语言标识符 (如果后面紧跟空白字符)
        text = re.sub(r"```(?:[a-zA-Z0-9+\-]*\s+)?([\s\S]*?)```", r"\1", text)

        # 移除行内代码 `code` -> code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        
        # 移除粗体/斜体 - 优化以避免误伤数学公式
        # Bold: **text** or __text__
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"__([^_]+)__", r"\1", text)
        
        # Italic: *text* or _text_
        # 严格模式: * 前后不能有空格 (CommonMark 标准)，且 * 必须位于词边界或非单词字符旁
        text = re.sub(r"(^|[^\w\*])\*(?!\s)([^*]+)(?<!\s)\*(?=$|[^\w\*])", r"\1\2", text)
        text = re.sub(r"(^|[^\w_])_(?!\s)([^_]+)(?<!\s)_(?=$|[^\w_])", r"\1\2", text)
        
        # 移除标题 (移除 # 但保留文本)
        text = re.sub(r"^(#{1,6})\s+(.*)", r"\2", text, flags=re.MULTILINE)
        
        # 移除引用 (移除 > 但保留文本)
        text = re.sub(r"^>\s+(.*)", r"\1", text, flags=re.MULTILINE)
        
        # 移除链接 [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        
        # 移除列表标记 (移除行首的 - 或 *)
        text = re.sub(r"^\s*[-*]\s+(.*)", r"\1", text, flags=re.MULTILINE)
        
        return text
