from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import LLMResponse
from astrbot.api import logger, AstrBotConfig
import re

# 模型偶尔漏出的 XML/CDATA 残留：CDATA 开头标记、"]]>" 及紧跟的闭合标签、回复末尾孤立的闭合标签
LEAKED_MARKUP_RE = re.compile(
    r"<!\[CDATA\[|\]\]>(?:\s*</[A-Za-z][\w:-]*>)*|(?:\s*</[A-Za-z][\w:-]*>)+\s*$"
)

@register("astrbot_plugin_markdown_killer", "AlanBacker", "移除输出中的Markdown格式（添加全局控制开关）", "0.0.7", "https://github.com/AlanBacker/astrbot_plugin_markdown_killer")
class MarkdownKillerPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
    
    @filter.on_llm_response()
    async def on_llm_resp(self, event: AstrMessageEvent, resp: LLMResponse, *args):
        """
        监听LLM回复，移除Markdown格式
        """
        if not resp or not resp.completion_text:
            return

        original_text = resp.completion_text
        
        # 调试日志：显示收到的原始文本，以便确认 LLM 是否输出了 Markdown
        # original_preview_debug = original_text[:50].replace('\n', '\\n')
        # logger.info(f"[Markdown Killer] 收到 LLM 回复 (前50字符): {original_preview_debug}...")
        
        cleaned_text = self.remove_markdown(original_text)
        
        if original_text != cleaned_text:
            resp.completion_text = cleaned_text
            # 使用 logger 提醒
            original_preview = original_text[:50].replace('\n', '\\n')
            cleaned_preview = cleaned_text[:50].replace('\n', '\\n')
            log_msg = f"\n[Markdown Killer] --------------------------------------------------\n[Markdown Killer] 检测到Markdown并移除:\n[Markdown Killer] 原文: {original_preview}...\n[Markdown Killer] 处理: {cleaned_preview}...\n[Markdown Killer] --------------------------------------------------"
            logger.warning(log_msg)

    @filter.on_agent_done()
    async def on_agent_done(self, event: AstrMessageEvent, run_context, resp: LLMResponse):
        """
        清除模型偶尔漏出的 XML/CDATA 残留（例如回复末尾的 ]]></text>）。
        同时改要发送的文本和存进对话历史的这条回复：历史里留着残留，模型下次会照着抄。
        """
        if not self.config.get("strip_leaked_markup", True):
            return

        if resp and resp.completion_text:
            cleaned = self.strip_leaked_markup(resp.completion_text)
            if cleaned != resp.completion_text:
                logger.warning(f"[Markdown Killer] 移除了回复里的标记残留: {resp.completion_text[-60:]!r} -> {cleaned[-60:]!r}")
                resp.completion_text = cleaned

        # 历史保存的是 run_context.messages，最后一条就是本次回复（在这个钩子之前追加）
        messages = getattr(run_context, "messages", None) or []
        last = messages[-1] if messages else None
        if getattr(last, "role", None) != "assistant":
            return
        if isinstance(last.content, str):
            last.content = self.strip_leaked_markup(last.content)
            return
        for part in last.content or []:
            text = getattr(part, "text", None)
            if isinstance(text, str):
                part.text = self.strip_leaked_markup(text)

    def strip_leaked_markup(self, text: str) -> str:
        """
        移除 XML/CDATA 残留；没有残留时原样返回（不动首尾空白）
        """
        cleaned = LEAKED_MARKUP_RE.sub("", text)
        return cleaned.rstrip() if cleaned != text else text

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        """
        监听所有即将发送出的消息，当开关开启时，进行全局 Markdown 移除
        """
        if not self.config.get("enable_global_markdown_killer", False):
            return
            
        result = event.get_result()
        if hasattr(result, "chain") and result.chain:
            for comp in result.chain:
                # 只对具有 text 属性的消息段进行处理（例如 Plain 或 TextPart 等）
                text = getattr(comp, "text", None)
                if isinstance(text, str):
                    cleaned = self.remove_markdown(text)
                    if cleaned != text:
                        comp.text = cleaned
                        original_preview = text[:50].replace('\n', '\\n')
                        cleaned_preview = cleaned[:50].replace('\n', '\\n')
                        log_msg = f"\n[Markdown Killer] --------------------------------------------------\n[Markdown Killer] [全局过滤] 检测到Markdown并移除:\n[Markdown Killer] 原文: {original_preview}...\n[Markdown Killer] 处理: {cleaned_preview}...\n[Markdown Killer] --------------------------------------------------"
                        logger.warning(log_msg)

    def remove_markdown(self, text: str) -> str:
        """
        移除文本中的Markdown格式
        """
        # 移除代码块 (保留内容)
        text = re.sub(r"```(?:[a-zA-Z0-9+\-]*\s+)?([\s\S]*?)```", r"\1", text)

        # 移除行内代码 `code` -> code
        text = re.sub(r"`([^`]+)`", r"\1", text)
        
        # 移除图片 ![alt](url) -> alt (提前于普通链接处理避免残留 "!")
        text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
        
        # 移除普通链接 [text](url) -> text
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        
        # 移除粗体 - 使用非贪婪匹配以支持内部包含特殊符号的情况
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        
        # 移除斜体 - 严格模式，避免误伤数学公式 (3 * 4 = 12) 或变量名 (this_is_var)
        text = re.sub(r"(?<!\*)\*(?!\s)(.*?)(?<!\s)\*(?!\*)", r"\1", text)
        text = re.sub(r"(?<!\w)_(?!\s)(.*?)(?<!\s)_(?!\w)", r"\1", text)
        
        # 移除删除线
        text = re.sub(r"~~(.*?)~~", r"\1", text)
        
        # 移除标题 (包含多级标题)
        text = re.sub(r"^(#{1,6})\s+(.*)", r"\2", text, flags=re.MULTILINE)
        
        # 移除引用 (处理嵌套情况: >>> text -> text)
        text = re.sub(r"^(?:>\s*)+(.*)", r"\1", text, flags=re.MULTILINE)
        
        # 移除列表标记 (移除行首的 -, *, +)
        text = re.sub(r"^\s*[-*+]\s+(.*)", r"\1", text, flags=re.MULTILINE)
        
        return text
