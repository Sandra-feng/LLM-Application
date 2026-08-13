#!/usr/bin/env python
# -*- encoding: utf-8 -*-
"""
@File         : fuzzy_match.py
@Description  : pdf切片溯源高亮
@Author       : tanxinji
@Date         : 2025/06/05 17:25:51
"""

import re, os, sys, math
from pymupdf import mupdf, JM_new_buffer_from_stext_page, JM_char_bbox, JM_rects_overlap, JM_char_quad, JM_quad_from_py, \
    hdist, vdist, Quad
import pkuseg
from pkuseg.config import config
from pkuseg.feature_extractor import FeatureExtractor
from pkuseg.model import Model
import pkuseg.inference as _inf
from rapidfuzz import fuzz
import numpy as np
import wordninja
from pkuseg import Preprocesser, Postprocesser, Postag

from base_utils.log_util import LogUtil

from loguru import logger
# logger = loguru logger (auto-migrated)
model_name="default"
config.modelDir = os.path.join(
    os.path.dirname(sys.modules["pkuseg"].__file__),
    # os.path.dirname(os.path.realpath(__file__)),
    "models",
    model_name,
)
default_name = os.path.join(
    os.path.dirname(sys.modules["pkuseg"].__file__),
    "dicts", "default.pkl",
)
feature_extractor = FeatureExtractor.load()
model = Model.load()
idx_to_tag = {
    idx: tag for tag, idx in feature_extractor.tag_to_idx.items()
}
# 修正比率，越大计算量越高
rectify_rate = 0.1


def _cut_v2(text):
    """
    直接对文本分词
    """
    examples = list(feature_extractor.normalize_text(text))
    length = len(examples)

    all_feature = []  # type: List[List[int]]
    for idx in range(length):
        node_feature_idx = feature_extractor.get_node_features_idx(
            idx, examples
        )
        all_feature.append(node_feature_idx)
    _, tags = _inf.decodeViterbi_fast(all_feature, model)
    # pos是位置列表（0开头）
    words = []
    pos = []
    current_word = None
    is_start = True
    pos_count = 0
    for tag, char in zip(tags, text):
        if is_start:
            current_word = char
            is_start = False
        elif "B" in idx_to_tag[tag]:
            words.append(current_word)
            pos.append(pos_count)
            current_word = char
        else:
            current_word += char
        pos_count += 1
    if current_word:
        words.append(current_word)
        pos.append(pos_count)

    if pos:
        pos.insert(0, 0)
        pos.pop()

    return words, pos

def cut_smart(text):
    """分词，结果返回一个list"""
    preprocesser = Preprocesser(None)
    postprocesser = Postprocesser(None, [default_name])
    txt = text.strip()

    ret = []
    usertags = []

    if not txt:
        return ret

    imary = txt.split()  # 根据空格分为多个片段

    # 对每个片段分词
    for w0 in imary:
        if not w0:
            continue

        # 根据用户词典拆成更多片段
        lst, isword, taglst = preprocesser.solve(w0)

        for w, isw, usertag in zip(lst, isword, taglst):
            if isw:
                ret.append(w)
                usertags.append(usertag)
                continue

            output = _cut_v2(w)[0]
            post_output = postprocesser(output)
            ret.extend(post_output)

    return ret

def accurate_cut_with_pos(text):
    seg = pkuseg.pkuseg()
    words = seg.cut(text)

    words_result = []
    pos_result = []
    pos = 0
    text_length = len(text)

    for word in words:
        word_len = len(word)
        if word_len == 0:
            continue

            # 在剩余文本中查找词语
        while pos < text_length:
            start = text.find(word, pos)
            if start == -1:
                # 处理分词错误情况
                words_result.append(word)
                pos_result.append( -1)
                break

                # 检查找到的词是否是完整分词（避免部分匹配）
            valid = True
            if start > pos:
                # 检查中间是否有未分词的字符
                skipped = text[pos:start]
                if skipped.strip():  # 如果有非空格字符
                    valid = False

            if valid:
                words_result.append(word)
                pos_result.append(start)
                pos = start + word_len
                break
            else:
                pos = start + 1  # 跳过这个位置继续查找

    # 进一步分词，处理标点符号和英文连起来的情况
    pos_ans = []
    words_ans = []
    for index, word in enumerate(words_result):
        if any('\u4e00' <= char <= '\u9fff' for char in word):
            # 如果这个词里面有中文因素，则直接加入
            pos_ans.append(pos_result[index])
            words_ans.append(word)
        else:
            # 如果有英文因素，进一步分词
            words_enhance = wordninja.split(word)
            accumulated_char = 0
            for word_in in words_enhance:
                pos_ans.append(pos_result[index] + accumulated_char)
                accumulated_char += len(word_in)
                words_ans.append(word_in)

    return words_ans, pos_ans

def safe_wordninja_split(text):
    # 检查是否包含非ASCII字符
    if not text.isascii():
        return [text]  # 返回原始字符串作为单个元素
    return wordninja.split(text)

def suffix_prefix_match(a: str, b: str):
    """
    将a的后缀与b的前缀的进行模糊匹配
    返回值：匹配子串在a和b的起始与结束位置（不包含）
    """
    # a = a.rstrip()
    # b = b.rstrip()
    # len_a = len(a)
    # len_b = len(b)
    # score = []
    # for l in range(1, min(len_a, len_b) + 1):
    #     score.append(fuzz.ratio(a[-l:], b[:l]))
    #
    # similarities = np.array(score)
    # # 找到最佳匹配
    # best_idx = similarities.argmax()
    #
    # return len(a) - int(best_idx) - 1, int(best_idx) + 1
    a_split, a_start_pos, a_end_pos = split_text(a)
    b_split, b_start_pos, b_end_pos = split_text(b)
    len_a = len(a_split)
    len_b = len(b_split)
    score = []
    for l in range(1, min(len_a, len_b) + 1):
        score.append(fuzz.ratio("".join(a_split[-l:]), "".join(b_split[:l])))
    similarities = np.array(score)
    # 找到最佳匹配
    best_idx = int(similarities.argmax())

    return a_start_pos[-1 * (best_idx + 1)], b_end_pos[best_idx]
def quads_to_rect(quads_ans):
    for _, quads in quads_ans.items():
        if not quads:
            continue
        items = len(quads)
        for i in range(items):
            q = Quad(quads[i])
            quads[i] = q.rect
        i = 0
        while i < items - 1:
            v1 = quads[i]
            v2 = quads[i + 1]
            if v1.y1 != v2.y1 or (v1 & v2).is_empty:
                i += 1
                continue
            quads[i] = v1 | v2
            del quads[i + 1]
            items -= 1
    return quads_ans
def fuzzy_match_template(long_text, template, re_a=0.05, re_min=13, re_max=50):
    """
    在长文本中模糊匹配最相似的子串（滑动窗口 + 余弦相似度）
    :param long_text: 待搜索的长文本
    :param template: 模板串
    :param re_a: 调整窗口大小的比率
    :param re_min: 最小的调整窗口大小，当切片过小时，可能会用到
    :param re_max: 最大的调整窗口大小，当切片过大时，可能会用到
    :return: (最佳匹配子串, 相似度分数)
    """
    # 分词
    seg = split_text  # 不返回
    seg_smart = split_text
    # seg_smart = pkuseg.pkuseg(postag=True).cut
    post_pattern_seg = seg_smart(template)[0]
    # post_pattern_seg = []
    # for word in pre_pattern_seg:
    #     temp_ans = safe_wordninja_split(word)
    #     for word_in in temp_ans:
    #         post_pattern_seg.append(word_in)
    # window_size = len(seg(template)[0])
    window_size = len(post_pattern_seg)

    template_enhance = ""
    for temp_word in post_pattern_seg:
        # if not any('\u4e00' <= char <= '\u9fff' for char in temp_word):
        #     # 如果没有中文字符，则加空格
        #     template_enhance += f" {temp_word}"
        # else:
        #     template_enhance += temp_word
        template_enhance += temp_word
    # new_pattern =
    # tokenizer = lambda text: seg(text)[0]
    # logger.info(f"加强后的匹配切片：{repr(template_enhance)}")
    # 这里要记录分词在原文的位置
    words, pos, rear = seg(long_text)
    # 若模板串长度接近甚至超过母串，则直接返回母串
    if window_size >= len(words):
        return 0, len(long_text.strip())

    # 滑动窗口大小列表
    adjust_size = math.ceil(window_size * re_a)
    adjust_size = re_min if adjust_size < re_min else adjust_size
    if adjust_size > 200:
        adjust_size = 100
    else:
        adjust_size = re_max if adjust_size > re_max else adjust_size
    window_list = [window_size - i for i in range(adjust_size, 0, -1)] + [window_size + i for i in range(adjust_size + 1)]
    window_list = [i for i in window_list if i > 0]
    # 滑动窗口生成候选子串
    candidates = []
    candi_pos = []
    candi_rear = []
    for window in window_list:
        for i in range(len(words) - window + 1):
            wait_for_join = words[i:i + window]
            candidate = ""
            for temp_word in wait_for_join:
                # if not any('\u4e00' <= char <= '\u9fff' for char in temp_word):
                #     # 如果没有中文字符，则加空格
                #     candidate += f" {temp_word}"
                # else:
                #     candidate += temp_word
                candidate += temp_word
            # candidate = "".join(words[i:i + window])  # 中文需拼接
            candidates.append(candidate)
            candi_pos.append(pos[i])
            candi_rear.append(rear[i + window - 1])

    # # 向量化（TF-IDF）
    # vectorizer = TfidfVectorizer(tokenizer=tokenizer, token_pattern=None)
    # corpus = [template] + candidates
    # tfidf_matrix = vectorizer.fit_transform(corpus)
    #
    # # 计算所有候选子串与模板的相似度
    # similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

    # 使用rapidfuzz计算相似度
    similarities = np.array([fuzz.ratio(template_enhance,  candidate) for candidate in candidates])

    # 找到最佳匹配
    best_idx = similarities.argmax()
    best_match = candidates[best_idx]
    # logger.info(f"最佳串：{repr(best_match)}")
    best_score = similarities[best_idx]
    best_pos = candi_pos[best_idx]
    best_rear = candi_rear[best_idx]

    # return best_match, best_score, best_pos
    return best_pos, best_rear

def split_text(text):
    # 正则表达式模式，用于匹配中文、英文单词和数字
    pattern = r'[\u4e00-\u9fff]|[a-zA-Z0-9]|[。%！？《》#@]'
    # 使用findall方法根据模式匹配文本
    pre_seg = re.findall(pattern, text)

    # 进一步分词，处理标点符号和英文连起来的情况
    # words_result = []
    # for index, word in enumerate(pre_seg):
    #     if any('\u4e00' <= char <= '\u9fff' for char in word):
    #         # 如果这个词里面有中文因素，则直接加入
    #         words_result.append(word)
    #     else:
    #         # 如果有英文因素，进一步分词
    #         words_enhance = wordninja.split(word)
    #         for word_in in words_enhance:
    #             words_result.append(word_in)
    words_result = pre_seg

    # 获取分割后的位置参数
    words_ans = []
    pos_ans = []
    rear_ans = []
    pos = 0
    text_length = len(text)

    for word in words_result:
        word_len = len(word)
        if word_len == 0:
            continue

        # 在剩余文本中查找词语
        while pos < text_length:
            start = text.find(word, pos)
            if start == -1:
                # 处理分词错误情况
                words_ans.append(word)
                pos_ans.append(-1)
                break

            words_ans.append(word)
            pos_ans.append(start)
            rear_ans.append(start + len(word))
            pos = start + word_len
            break
    return words_ans, pos_ans, rear_ans

def string_of_page(page):
    """返回一页中的文本字符"""
    return mupdf.fz_string_from_buffer(JM_new_buffer_from_stext_page(page))

def JM_search_stext_page_v3(char_join, begin, end, page_dict):
    """
    跨页获取高亮区域
    :param char_join: 合并的字符串
    :param begin: 需要高亮的字符串起始
    :param end: 需要高亮的字符串结尾（不包含）
    :page_dict: 页数据
    :return: 一个列表，对应每一页需要高亮的区域
    """
    page_num_list = [k for k, _ in page_dict.items()]
    quads = {page_num: [] for page_num in page_num_list}
    class Hits:
        def __str__(self):
            return f'Hits(len={self.len} hfuzz={self.hfuzz} vfuzz={self.vfuzz}'

    hits = Hits()
    hits.len = 0
    hits.hfuzz = 0.2  # merge kerns but not large gaps
    hits.vfuzz = 0.1


    haystack = 0
    inside = 0
    i = 0
    for page_num, page in page_dict.items():
        page = page.get_textpage().this
        rect = mupdf.FzRect(page.m_internal.mediabox)
        for block in page:
            if block.m_internal.type != mupdf.FZ_STEXT_BLOCK_TEXT:
                continue
            for line in block:
                for ch in line:
                    i += 1
                    if not mupdf.fz_is_infinite_rect(rect):
                        r = JM_char_bbox(line, ch)
                        if not JM_rects_overlap(rect, r):
                            continue

                    if not inside:
                        if haystack >= begin:
                            inside = 1
                    if inside:
                        if haystack < end:
                            # 匹配到了，进行高亮区域的设置与合并
                            vfuzz = ch.m_internal.size * hits.vfuzz
                            hfuzz = ch.m_internal.size * hits.hfuzz
                            ch_quad = JM_char_quad(line, ch)
                            if quads.get(page_num):
                                # 若行内的高亮区域达到阈值，且在同一页，则合并高亮区域
                                quad = quads.get(page_num)[-1]
                                end_quad = JM_quad_from_py(quad)
                                if (1
                                        and hdist(line.m_internal.dir, end_quad.lr, ch_quad.ll) < hfuzz
                                        and vdist(line.m_internal.dir, end_quad.lr, ch_quad.ll) < vfuzz
                                        and hdist(line.m_internal.dir, end_quad.ur, ch_quad.ul) < hfuzz
                                        and vdist(line.m_internal.dir, end_quad.ur, ch_quad.ul) < vfuzz
                                    ):
                                    end_quad.ur = ch_quad.ur
                                    end_quad.lr = ch_quad.lr
                                    assert quads.get(page_num)[-1] == end_quad
                                    haystack += 1
                                    continue
                            quads[page_num].append(ch_quad)
                            hits.len += 1
                        else:
                            return quads
                    haystack += 1
                    # 下一个字符
                assert char_join[haystack] == '\n', \
                    f'{haystack=} {char_join[haystack]=}'
                haystack += 1
            assert char_join[haystack] == '\n', \
                f'{haystack=} {char_join[haystack]=}'
            haystack += 1
    return quads

def JM_search_stext_page_v4(char_join, begin, end, page_dict):
    """
    跨页获取高亮区域
    :param char_join: 提取出的buffer
    :param begin: 需要高亮的字符串起始
    :param end: 需要高亮的字符串结尾（不包含）
    :page_dict: 页数据
    :return: 一个列表，对应每一页需要高亮的区域
    """
    page_num_list = [k for k, _ in page_dict.items()]
    quads = {page_num: [] for page_num in page_num_list}
    class Hits:
        def __str__(self):
            return f'Hits(len={self.len} hfuzz={self.hfuzz} vfuzz={self.vfuzz}'

    hits = Hits()
    hits.len = 0
    hits.hfuzz = 0.2  # merge kerns but not large gaps
    hits.vfuzz = 0.1


    haystack = 0
    inside = 0
    i = 0
    for page_num, page in page_dict.items():
        page = page.get_textpage().this
        rect = mupdf.FzRect(page.m_internal.mediabox)
        for block in page:
            if block.m_internal.type != mupdf.FZ_STEXT_BLOCK_TEXT:
                continue
            for line in block:
                for ch in line:
                    i += 1
                    if not mupdf.fz_is_infinite_rect(rect):
                        r = JM_char_bbox(line, ch)
                        if not JM_rects_overlap(rect, r):
                            continue

                    if not inside:
                        if haystack >= begin:
                            inside = 1
                    if inside:
                        if haystack < end:
                            # 匹配到了，进行高亮区域的设置与合并
                            vfuzz = ch.m_internal.size * hits.vfuzz
                            hfuzz = ch.m_internal.size * hits.hfuzz
                            ch_quad = JM_char_quad(line, ch)
                            if quads.get(page_num):
                                # 若行内的高亮区域达到阈值，且在同一页，则合并高亮区域
                                quad = quads.get(page_num)[-1]
                                end_quad = JM_quad_from_py(quad)
                                if (1
                                        and hdist(line.m_internal.dir, end_quad.lr, ch_quad.ll) < hfuzz
                                        and vdist(line.m_internal.dir, end_quad.lr, ch_quad.ll) < vfuzz
                                        and hdist(line.m_internal.dir, end_quad.ur, ch_quad.ul) < hfuzz
                                        and vdist(line.m_internal.dir, end_quad.ur, ch_quad.ul) < vfuzz
                                    ):
                                    end_quad.ur = ch_quad.ur
                                    end_quad.lr = ch_quad.lr
                                    assert quads.get(page_num)[-1] == end_quad
                                    haystack += 1
                                    continue
                            quads[page_num].append(ch_quad)
                            hits.len += 1
                        else:
                            return quads
                    haystack += 1
                    # 下一个字符
                # assert char_join[haystack] == '\n', \
                #     f'{haystack=} {char_join[haystack]=}'
                haystack += 1
            # assert char_join[haystack] == '\n', \
            #     f'{haystack=} {char_join[haystack]=}'
            haystack += 1
    return quads

if __name__ == '__main__':
    # 示例使用
    pattern = "## 中华人民共和国网络安全法\n（2016年11月7日第十二届全国人民代表大会常务委 员会第二十四次会"
    "议通过）\n## 目录\n第一章总则 第二章 网络安全支持与促进 第三章网络运行安全 第一节一般规定 第"
    "二节关键信息基础设施的运行安全 第四章网络信息安全 第五章监测预警与应急处置 第六章法律责任 第七"
    "章附则\n## 第一章总则\n第一条为了保障网络安全，维护网络空间主权和国家安全、 社会公共利益，保护"
    "公民、法人和其他组织的合法权益，促进经济社会信息化健康发展，制定本法。\n第二条在中华人民共和国境"
    "内建设、运营、维护和使用网 络，以及网络安全的监督管理，适用本法。\n第三条国家坚持网络安全与信息"
    "化发展并重，遵循积极利 用、科学发展、依法管理、确保安全的方针，推进网络基础设施 建设和互联互通"
    "，鼓励网络技术创新和应用，支持培养网络安全 人才，建立健全网络安全保障体系，提高网络安全保护能力"
    "。\n第四条国家制定并不断完善网络安全战略，明确保障网络 安全的基本要求和主要目标，提出重点领域的"
    "网络安全政策、工 作任务和措施。"
    pattern2 = "## 中华人民共和国网络安全法\n（2016年11月7日第十二届全国人民代表大会常务委 员会第二十四次会"\
               "议通过）\n## 目录\n第一章总则 第二章 网络安全支持与促进"
    haystack_string = "—1—\n\n中华人民共和国网络安全法\n\n（2016 年11 月7 日第十二届全国人民代表大会常务委"\
                      "\n\n员会第二十四次会议通过）"\
                      "\n目\n录\n\n第一章\n总则\n\n第二章\n网络安全支持与促进\n\n第三章\n网络运行安全\n\n第一节\n一般规定\n\n第二节\n关键信息基础设施的运行安全"\
                      "\n\n第四章\n网络信息安全\n\n第五章\n监测预警与应急处置\n\n第六章\n法律责任\n\n第七章\n附则\n\n第一章\n总则\n\n第一条\n为"\
                      "了保障网络安全，维护网络空间主权和国家安全、\n\n社会公共利益，保护公民、法人和其他组织的合法权益，促进经\n\n\n"
    long_text = "今天是晴天，适合户外fff运动。明天可能是阴天，但后天又会转晴。but you have to do me."
    template = "明天是阴天"

    # begin, end = fuzzy_match_template(haystack_string, pattern2, re_a=rectify_rate)
    print(split_text(long_text))
