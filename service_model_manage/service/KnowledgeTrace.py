import re

from loguru import logger


class KnowledgeTrace:
    def __init__(self):
        self.flag = 0  # 是否缓存状态
        self.temp_token = ""  # 缓存 <citation> 中的内容
        self.content_type = "text"
        self.text_num = 0
        self.citation_info = []
        self.content = ""
        self.temp_content = ""
        self.open_delim = None  # 当前缓存的起始分隔符（"<" 或 "[")
        # 统一并预编译 citation 正则，匹配 <citation:...> 或 [citation:...]
        self.citation_pattern = re.compile(r"(?:<citation[:|：](.*?)>|\[citation[:|：](.*?)\])")

    def process_token_citation(self, token, content_type, think_time):
        """
        处理 citation 标签
        返回: (skip_token, token, results)
        """
        try:
            results = []
            self.temp_content += token
            self.content_type = content_type

            # 局部工具：折叠相邻且内容完全相同的非 citation 方括号，如 "[2024版][2024版]" -> "[2024版]"
            def _collapse_duplicate_brackets(s: str) -> str:
                # 精简为仅在当前字符串内部压缩相邻重复的非 citation 方括号
                
                # 在字符串内部压缩相邻重复的非 citation 方括号
                out_parts = []
                pos = 0
                last_br = None
                last_was_br = False
                for m in re.finditer(r"\[([^\]]+)\]", s):
                    # 添加括号前的普通文本
                    non_br_text = s[pos : m.start()]
                    if non_br_text:
                        out_parts.append(non_br_text)
                        last_was_br = False
                        last_br = None

                    curr_inner = m.group(1)
                    curr_token = f"[{curr_inner}]"
                    # 跳过非 citation 的相邻重复括号
                    if last_was_br and last_br == curr_inner and not str(curr_inner).strip().lower().startswith("citation"):
                        # 跳过该重复括号
                        pass
                    else:
                        out_parts.append(curr_token)
                        last_was_br = True
                        last_br = curr_inner
                    pos = m.end()

                # 添加剩余尾部
                out_parts.append(s[pos:])
                return "".join(out_parts)

            # 3. 如果 flag！=0 表示还在缓存状态
            if self.flag != 0:
                self.temp_token += token
                # 根据起始分隔符判断是否结束（">" 或 "]"）
                close_char = ">" if self.open_delim == "<" else "]" if self.open_delim == "[" else None
                if close_char and close_char in token:  # 缓存结束
                    self.flag = 0  # 输出态
                    # 使用统一的预编译正则进行匹配
                    m = self.citation_pattern.search(self.temp_token)
                    if m:
                            # # citation 前的普通文本作为 text 事件输出
                            # prefix_text = self.temp_token[: m.start()]
                            # prefix_text = _collapse_duplicate_brackets(prefix_text)
                            # if prefix_text:
                            #     results.append({"token": prefix_text, "type": self.content_type, "think_time": think_time})
                            # citation 数字事件
                            b_content = m.group(1) if m.group(1) is not None else m.group(2)
                            for num_str in re.findall(r"\d+", b_content):
                                idx = int(num_str)
                                results.append({"token": idx, "type": "citation", "think_time": think_time})
                            # citation 后尾部文本
                            tail = self.temp_token[m.end():]
                            tail = _collapse_duplicate_brackets(tail)
                            self.temp_token = ""
                            if tail:
                                token = tail
                                results.append({"token": token, "type": self.content_type, "think_time": think_time})
                            # 重置分隔符
                            self.open_delim = None
                            self.temp_token = ""
                            return False, token, results
                    else:
                        # 未匹配到完整 citation，按普通文本处理（包括非 citation 情况）
                        appended = _collapse_duplicate_brackets(self.temp_token)
                        results.append({"token": appended, "type": self.content_type, "think_time": think_time})
                        self.open_delim = None
                        self.temp_token = ""
                        return False, token, results
                else:#累积未完成，比如"itatio",还没累积完
                    # return true表示跳过输出当前token,进行流式吐出token
                    return True, token, results

            # 1. 遇到 "<" 或 "[" ，进入缓存状态,从这里出去的都已经没有前缀了
            if "<" in token or "[" in token:
                self.flag = 1  # 缓存态
                lt_idx = token.find("<") if "<" in token else -1
                lb_idx = token.find("[") if "[" in token else -1
                # 选择最先出现的分隔符位置
                if lt_idx == -1:
                    open_idx = lb_idx
                    self.open_delim = "["#记录装饰符
                elif lb_idx == -1:
                    open_idx = lt_idx
                    self.open_delim = "<"
                else:
                    open_idx = lt_idx if lt_idx < lb_idx else lb_idx
                    self.open_delim = "<" if lt_idx < lb_idx else "["

                prefix = token[:open_idx]
                if prefix:  # 说明 < 前有前缀普通文本,输出前缀
                    results.append({"token": prefix, "type": self.content_type, "think_time": think_time})
                # 判断是否在同一个token内直接闭合
                close_char = ">" if self.open_delim == "<" else "]"
                if close_char not in token: #没有闭合情况
                    if prefix:  # 说明 < 前有前缀普通文本,处理前缀
                        # 剩余部分进入缓存
                        tmp = token[open_idx:] #eg:<cita
                        if tmp:
                            self.temp_token += tmp
                        return False, token, results
                    else:  # <没有前缀,直接缓存
                        self.flag = 1
                        self.temp_token += token
                        return True, token, results
                else:  # token 中出现闭合符（可能是 <citation:...> 或 [citation:...] ）
                    # 统一使用预编译正则检测是否是引用注释
                    m = self.citation_pattern.search(token)
                    if m:
                            # citation 数字事件
                            b_content = m.group(1) if m.group(1) is not None else m.group(2)
                            for num_str in re.findall(r"\d+", b_content):
                                idx = int(num_str)
                                results.append({"token": idx, "type": "citation", "think_time": think_time})
                            # 尾部文本
                            tail = token[m.end():]
                            tail = _collapse_duplicate_brackets(tail)
                            self.temp_token = ""
                            self.flag = 0  # 输出态
                            if tail:
                                token = tail
                                results.append({"token": token, "type": self.content_type, "think_time": think_time})
                            # 重置分隔符
                            self.open_delim = None
                            return False, token, results
                    else:
                        # 未匹配到完整 citation，按普通文本输出（包括非 citation 情况）
                        self.flag = 0
                        self.temp_token=""
                        appended = token[open_idx:] if 'open_idx' in locals() else token
                        appended = _collapse_duplicate_brackets(appended)
                        results.append({"token": appended, "type": self.content_type, "think_time": think_time})
                        self.open_delim = None
                        return False, appended, results

            else:# 4. 正常正文
                results.append({"token": token, "type": self.content_type, "think_time": think_time})

            return False, token, results

        except Exception as e:
            # 记录错误信息，包括异常类型和详细信息
            logger.error(f"process_token方法出错: {str(e)}", exc_info=True)
            # 可以根据需要返回默认值或重新引发异常
            # 这里返回原始参数和默认状态，以便调用方处理
            return False, token, []

    @staticmethod
    def process_content(text):
        """
        处理文本中的 citation 标签，提取引用数字并返回清理后的文本和引用列表。
        """
        citation_numbers = []

        # 预编译正则，匹配 <citation:...> 或 [citation:...]
        pattern = re.compile(r"(?:<citation[:|：](.*?)>|\[citation[:|：](.*?)\])")

        # 先收集所有匹配，避免在替换过程中位置发生变化
        matches = list(pattern.finditer(text))

        # 计算清理后文本中的准确位置：原始起始位置 - 之前被删除的总长度
        removed_so_far = 0
        for m in matches:
            content = m.group(1) if m.group(1) is not None else m.group(2)
            numbers = re.findall(r"\d+", content)
            adjusted_pos = m.start() - removed_so_far
            for num in numbers:
                citation_numbers.append({"position": int(adjusted_pos), "citation": int(num)})
            removed_so_far += m.end() - m.start()

        # 构建清理后的文本：移除所有匹配片段
        if not matches:
            return text, citation_numbers

        parts = []
        last_idx = 0
        for m in matches:
            parts.append(text[last_idx : m.start()])
            last_idx = m.end()
        parts.append(text[last_idx:])
        cleaned_text = "".join(parts)
        sorted_chunk_citation = sorted(citation_numbers, key=lambda x: (x["position"], -x["citation"]))
        return cleaned_text, sorted_chunk_citation


class ThinkingProcessor:
    def __init__(self, start_tag="<think>", end_tag="</think>"):
        self.start_tag = start_tag
        self.end_tag = end_tag
        self.in_thinking = 0  # 0=未开始，1=检测到起始符，2=思考中，3=中间态，4=结束
        self.tag_buf = ""  # 缓冲区
        self.content_type = "text"  # 当前内容类型
        self.count = 0  # chunk计数

    def process(self, token: str, is_think: bool):
        """
        处理单个token，识别是否处于思考区间。
        返回 (skip_token, token, content_type, in_thinking)
        """
        if not is_think:
            return False, token, "text", self.in_thinking

        self.count += 1
        self.tag_buf += token

        # 识别思考开始
        if self.in_thinking == 0 and self.count == 1 and "<" in token:
            self.in_thinking = 1
        elif self.in_thinking != 4:
            self.in_thinking = 2
            self.content_type = "thinking"

        # 出现 <think>
        if self.start_tag in self.tag_buf:
            self.in_thinking = 2
            self.content_type = "thinking"
            if len(self.tag_buf.split(self.start_tag)) > 1:
                token = self.tag_buf.split(self.start_tag)[-1]
            self.tag_buf = self.tag_buf.replace(self.start_tag, "")
        # 出现新的 <
        if self.in_thinking == 2 and "<" in self.tag_buf:
            self.in_thinking = 3
        # 出现 </think>
        if self.end_tag in self.tag_buf:
            self.in_thinking = 4
            self.content_type = "text"
            if len(self.tag_buf.split(self.end_tag)) > 1:
                token = self.tag_buf.split(self.end_tag)[-1]
            self.tag_buf = self.tag_buf.replace(self.end_tag, "")
        # 如果还在开始或中间状态，则跳过输出
        if self.in_thinking in (1, 3):
            return True, token, self.content_type, self.in_thinking

        return False, token, self.content_type, self.in_thinking


# def test_knowledge_trace():
#     tokens = [
#         "这是", "<think>", "模型正在思考", "更多推理", "</think>",
#         "回答开始。", "引用在", "<citation>[12]</citation>", "这里。"
#     ]
#
#     trace = KnowledgeTrace(start_time=time.time())
#
#     outputs = []
#     for t in tokens:
#         token, ttype = trace.process_token(t)
#         if token:
#             outputs.append((token, ttype))
#
#     print("输出序列:", outputs)
#     print("最终正文:", trace.content)
#     print("思考内容:", trace.think)
#     print("思考耗时:", trace.think_time)
#     print("引用信息:", trace.citation_info)
#
#
# if __name__ == "__main__":
#     test_knowledge_trace()
