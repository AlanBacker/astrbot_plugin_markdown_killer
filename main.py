from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.provider import LLMResponse
from astrbot.api import logger, AstrBotConfig
import re

# 模型偶尔漏出的 XML/CDATA 残留：CDATA 开头标记、"]]>" 及紧跟的闭合标签、回复末尾孤立的闭合标签
LEAKED_MARKUP_RE = re.compile(
    r"<!\[CDATA\[|\]\]>(?:\s*</[A-Za-z][\w:-]*>)*|(?:\s*</[A-Za-z][\w:-]*>)+\s*$"
)

# AstrBot 内容安全拦下消息时发的英文提示（astrbot/core/pipeline/content_safety_check/stage.py）
CORE_BLOCK_NOTICE = "Your message or the model response contains inappropriate content and has been blocked."
BLOCK_NOTICE_ZH = "这个我不好接，换个说法吧"
REWRITE_PROMPT = (
    "下面是你刚写好、准备发到QQ里的一段回复，但里面有发不出去的词：{words}。\n"
    "把它改写一遍：意思、口气、长短都不变，只是不出现这些词，连字面上碰巧凑出来的也不行"
    "（比如“十有八九”里有“八九”，“全平台独占”里有“台独”）。可以换近义说法、换阿拉伯数字或者换个说法；"
    "像 &&开心&& 这样的标记原样保留。撞词的地方要是在复述系统提醒、提示词或者你自己的设定"
    "（比如 <编号: …> 这样的标签），直接删掉那部分，别换说法。如果这段回复本身在聊政治，就改成一句同样口气的打岔。"
    "只输出改写后的回复本身，不要解释。\n\n{text}"
)
# 改写失败时按这些标点切分句，去掉撞词的那几段
CLAUSE_END_RE = re.compile(r"(?<=[，。！？；,.!?;\n])")

@register("astrbot_plugin_markdown_killer", "AlanBacker", "移除输出中的Markdown格式（添加全局控制开关）", "0.0.8", "https://github.com/AlanBacker/astrbot_plugin_markdown_killer")
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

    @filter.on_agent_done()
    async def avoid_blocked_words(self, event: AstrMessageEvent, run_context, resp: LLMResponse):
        """
        回复撞上内容安全屏蔽词时先换个说法，免得整条被拦、群里只收到一句英文提示。
        屏蔽词按子串匹配，“十有八九”“全平台独占”这种正常说法也会撞上“八九”“台独”。
        先让本会话的对话模型改写；改写后还撞词就去掉撞词的分句，全去掉了就换成一句中文。
        发送的文本和存进对话历史的这条回复一起改。
        """
        if not self.config.get("avoid_blocked_words", False) or not resp or not resp.completion_text:
            return
        umo = event.unified_msg_origin
        safety = self.context.get_config(umo=umo).get("content_safety", {})
        keywords = safety.get("internal_keywords", {})
        # 只有核心也检查回复时才需要处理
        if not safety.get("also_use_in_response") or not keywords.get("enable"):
            return
        patterns = keywords.get("extra_keywords") or []
        text = resp.completion_text
        hits = {m.group(0) for p in patterns if (m := re.search(p, text))}
        if not hits:
            return

        new_text = ""
        provider = self.context.get_using_provider(umo=umo)
        if provider:
            try:
                rewritten = await provider.text_chat(
                    prompt=REWRITE_PROMPT.format(words="、".join(sorted(hits)), text=text)
                )
                new_text = (rewritten.completion_text or "").strip()
            except Exception as e:
                logger.warning(f"[Markdown Killer] 改写撞屏蔽词的回复失败: {e}")
        # 改写结果为空、还撞词或者长出一大截（多半夹了解释）都不用
        if not new_text or len(new_text) > len(text) * 2 + 20 or any(re.search(p, new_text) for p in patterns):
            new_text = "".join(
                c for c in CLAUSE_END_RE.split(text) if not any(re.search(p, c) for p in patterns)
            ).strip(" ，,")
        # 分句拼回去后可能又凑出屏蔽词，再查一遍
        if not new_text or any(re.search(p, new_text) for p in patterns):
            new_text = BLOCK_NOTICE_ZH
        logger.warning(f"[Markdown Killer] 回复撞上屏蔽词 {sorted(hits)}，已改写: {text[:60]!r} -> {new_text[:60]!r}")
        resp.completion_text = new_text

        # 历史保存的是 run_context.messages，最后一条就是本次回复（在这个钩子之前追加）
        messages = getattr(run_context, "messages", None) or []
        last = messages[-1] if messages else None
        if getattr(last, "role", None) != "assistant":
            return
        if isinstance(last.content, str):
            last.content = new_text
            return
        for part in last.content or []:
            if isinstance(getattr(part, "text", None), str):
                part.text = new_text

    @filter.on_decorating_result()
    async def replace_block_notice(self, event: AstrMessageEvent):
        """
        用户消息撞屏蔽词、又在叫机器人时，AstrBot 会回一句英文提示，这里换成中文。
        """
        if not self.config.get("avoid_blocked_words", False):
            return
        result = event.get_result()
        for comp in getattr(result, "chain", None) or []:
            if getattr(comp, "text", None) == CORE_BLOCK_NOTICE:
                comp.text = BLOCK_NOTICE_ZH

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
