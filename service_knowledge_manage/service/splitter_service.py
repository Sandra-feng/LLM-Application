#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：splitter_service.py
@Author  ：zhoumin
@Date    ：2025-09-09
@Description: 文本分割服务，支持多种分割策略，与RAG服务无缝集成

该服务提供了多种文本分割策略，包括字符分割、递归分割、中文分割等，
主要用于将长文本分割成适合向量化和检索的chunks。
"""

from loguru import logger
import re
import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, Union
import string
from langchain_text_splitters import CharacterTextSplitter, RecursiveCharacterTextSplitter, SpacyTextSplitter
from langchain_text_splitters.base import TextSplitter
from collections import defaultdict
import uuid
from service_knowledge_manage.service.util.splitter import ChineseRecursiveTextSplitter
# logger = loguru logger (auto-migrated)
@dataclass
class ChunkMetadata:
    """Chunk元数据，用于追踪和CRUD操作"""

    start_pos: int = 0  # 在原文中的起始位置
    end_pos: int = 0  # 在原文中的结束位置
    chunk_index: int = 0  # chunk在分割结果中的索引
    page_number: Optional[int] = None  # 页码（如果有）
    file_name: str = ""  # 源文件名
    file_id: str = ""  # 文件ID
    chunk_size: int = 0  # chunk大小
    separator_used: str = ""  # 使用的分隔符
    split_method: str = ""  # 分割方法
    source_data: list[dict[str, Any]] = field(default_factory=list)  # 源数据（如图片URL等）
    chunk_split_type: str = ""
    parent_node:list=""
    chunk_id: str = ""
    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式"""
        return {
            "start_pos": self.start_pos,
            "end_pos": self.end_pos,
            "chunk_index": self.chunk_index,
            "page_number": self.page_number,
            "file_name": self.file_name,
            "file_id": self.file_id,
            "chunk_size": self.chunk_size,
            "separator_used": self.separator_used,
            "split_method": self.split_method,
            "source_data": self.source_data,
            "chunk_split_type":self.chunk_split_type,
            "parent_node": self.parent_node,
            "chunk_id": self.chunk_id,
        }


@dataclass
class Chunk:
    """文本块，包含内容和元数据"""

    content: str
    metadata: ChunkMetadata
    ori_content: str = ""  # 原始内容，在创建chunk时保存

    def to_dict(self) -> dict[str, Any]:
        """转换为字典格式，用于存储和传输"""
        return {"content": self.content, "metadata": self.metadata.to_dict()}


class BaseSplitter(ABC):
    """文本分割器基类"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, **kwargs):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.kwargs = kwargs

    @abstractmethod
    def split(
        self, text: list, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ) -> list[Chunk]:
        """分割文本，返回Chunk列表"""

        pass

    def _remove_newlines(self, s: str, separators: Optional[Union[str, list[str]]] = None) -> str:
        """去除换行符、空格符和指定的分隔符"""

        en_punct = string.punctuation  # !"#$%&'()*+,-./:;<=>?@[\]^_`{|}~

        # 2. 中文常用标点（按需增删）
        cn_punct = "，。！？、；：“”‘’（）【】《》〈〉「」﹃﹄〔〕…—～"

        # 3. 合并并生成翻译表
        all_punct = en_punct + cn_punct
        # str.maketrans 把每个标点映射到 None（即删除）
        trans_table = str.maketrans('', '', all_punct)

        # 4. 一键去标点
        result = s.replace("\n", "").replace(" ", "").translate(trans_table)
        # result = s.replace("\n", "").replace(" ", "")
        
        if separators is not None:
            if isinstance(separators, str):
                # 单个分隔符
                result = result.replace(separators, "")
            elif isinstance(separators, list):
                # 多个分隔符
                for sep in separators:
                    result = result.replace(sep, "")
        
        return result
    
    def split_v1_v2(self, node_list: list, separators: Optional[Union[str, list[str]]] = None):
        """
        第二种切分方案：创建去除换行符、空格符和分隔符的all_text2和对应的spans_node坐标
        
        Args:
            node_list: 节点列表
            separators: 要去除的分隔符，可以是字符串或字符串列表
        
        Returns:
            all_text: 原始拼接文本（保留换行符和空格）
            all_text2: 去除换行符、空格符和分隔符的拼接文本
            spans_node: 去除换行符、空格符和分隔符文本中每个node的坐标
        """
        # 1. 把所有 text node 拼接成 all_text
        all_text = ""

        for node in node_list:
            if node["type"] == "text":
                text_md = node.get("text", "")
                all_text += text_md
                all_text += "\n"

        # 2. 创建去除换行符、空格符和分隔符的all_text2和对应的spans_node坐标
        all_text2 = ""
        spans_node = []  # [(start, end, node_id, text)]
        
        for node in node_list:
            if node["type"] == "text":
                start = len(all_text2)
                text_md = node.get("text", "")
                # 去除换行符、空格符和分隔符
                text_no_newlines = self._remove_newlines(text_md, separators)
                all_text2 += text_no_newlines
                end = len(all_text2)
                spans_node.append((start, end, node["id"], text_no_newlines))

        return all_text, all_text2, spans_node
    
    def _find_chunk_position_v2(self, all_text2: str, chunk: str, start_pos: int, chunk_overlap: int, separators: Optional[Union[str, list[str]]] = None) -> int:
        """
        第二种切分方案的chunk位置查找：基于去除换行符、空格符和分隔符的all_text2
        
        Args:
            all_text2: 去除换行符、空格符和分隔符的拼接文本
            chunk: 要查找的chunk
            start_pos: 开始搜索的位置
            chunk_overlap: chunk重叠大小
            separators: 要去除的分隔符，可以是字符串或字符串列表
            
        Returns:
            chunk在all_text2中的起始位置
        """
        # 对chunk也去除换行符、空格符和分隔符
        chunk_no_newlines = self._remove_newlines(chunk, separators)
        
        # 计算搜索范围
        if start_pos - chunk_overlap <= 0:
            start = 0
        else:
            start = start_pos - chunk_overlap
            
        # 在all_text2中查找去除换行符、空格符和分隔符后的chunk
        pos = all_text2.find(chunk_no_newlines, start)
        
        if pos != -1:
            return pos
        
        # 如果找不到，使用相似度匹配作为兜底
        return self._find_by_similarity_improved(all_text2, chunk_no_newlines, start)
    
    def split_v2_v2(self, all_text2, spans_node, chunks, node_list, chunk_overlap, is_parent, i,separators: Optional[Union[str, list[str]]] = None):
        """
        第二种切分方案的v2版本：使用去除换行符、空格符和分隔符的文本进行chunk与node的匹配
        
        Args:
            all_text2: 去除换行符、空格符和分隔符的拼接文本
            spans_node: 去除换行符、空格符和分隔符文本中每个node的坐标
            chunks: 切分后的chunks
            node_list: 原始节点列表
            chunk_overlap: chunk重叠大小
            is_parent: 是否为父级切分
            separators: 要去除的分隔符，可以是字符串或字符串列表
            
        Returns:
            final_chunks: 最终的chunk列表
        """
        chunks_with_nodes = []
        last_pos = 0

        # 3. 建立 all_text2 中每个 chunk 与 node 的对应关系
        for chunk in chunks:
            # 使用新的查找方法，基于去除换行符、空格符和分隔符的文本
            start = self._find_chunk_position_v2(all_text2, chunk, last_pos, chunk_overlap, separators)
            end = start + len(self._remove_newlines(chunk, separators))
            last_pos = end

            included_nodes = []
            for s, e, nid, ntext in spans_node:
                if not (end <= s or start >= e):  # 有交集
                    included_nodes.append(nid)

            chunks_with_nodes.append({"type": "chunk_text", "content": chunk, "nodes": included_nodes})

        # 4. 把 table/image 插入到对应位置（与原方案相同）
        final_chunks = []

        for node in node_list:
            if node["type"] == "text":
                # 只在遇到第一个 text node 的时候，把相关 chunks 加进来
                related_chunks = [c for c in chunks_with_nodes if node["id"] in c["nodes"]]
                for rc in related_chunks:
                    if rc not in final_chunks:
                        final_chunks.append(rc)
            elif node["type"] == "table" and is_parent==True:
                is_ref = False
                for index, item_node in enumerate(node_list):
                    if node["id"] in item_node.get("referenced_tables", []):
                        is_ref = True
                        break
                    if index == len(node_list) - 1 and is_ref == False:
                        final_chunks.append(
                            {
                                "type": f"chunk_{node['type']}",
                                "content": node.get("text", "") if node["type"] == "table" else node.get("text", ""),
                                "nodes": [node["id"]],
                            }
                        )
                        break
            elif node["type"] == "image" and  is_parent==True:
                is_ref = False
                for index, item_node in enumerate(node_list):
                    if node["id"] in item_node.get("referenced_images", []):
                        is_ref = True
                        break
                    if index == len(node_list) - 1 and is_ref == False and node.get("text", "") != "":
                        final_chunks.append(
                            {
                                "type": f"chunk_{node['type']}",
                                "content": node.get("text", "") if node["type"] == "image" else node.get("text", ""),
                                "nodes": [node["id"]],
                            }
                        )
                        break
        return final_chunks

    def split_v3_v2(self, all_text2, spans_node, chunks, node_list, chunk_overlap, is_parent,
                    separators: Optional[Union[str, list[str]]] = None):
        """
        第二种切分方案的v2版本：使用去除换行符、空格符和分隔符的文本进行chunk与node的匹配

        Args:
            all_text2: 去除换行符、空格符和分隔符的拼接文本
            spans_node: 去除换行符、空格符和分隔符文本中每个node的坐标
            chunks: 切分后的chunks
            node_list: 原始节点列表
            chunk_overlap: chunk重叠大小
            is_parent: 是否为父级切分
            separators: 要去除的分隔符，可以是字符串或字符串列表

        Returns:
            final_chunks: 最终的chunk列表
        """
        chunks_with_nodes = []
        last_pos = 0

        # 3. 建立 all_text2 中每个 chunk 与 node 的对应关系
        for chunk in chunks:
            # 使用新的查找方法，基于去除换行符、空格符和分隔符的文本
            start = self._find_chunk_position_v2(all_text2, chunk, last_pos, chunk_overlap, separators)
            end = start + len(self._remove_newlines(chunk, separators))
            last_pos = end

            included_nodes = []
            for s, e, nid, ntext in spans_node:
                if not (end <= s or start >= e):  # 有交集
                    included_nodes.append(nid)

            chunks_with_nodes.append({"type": "chunk_text", "content": chunk, "nodes": included_nodes})

        # 4. 把 table/image 插入到对应位置（与原方案相同）
        final_chunks = []

        for node in node_list:
            if node["type"] == "text":
                # 只在遇到第一个 text node 的时候，把相关 chunks 加进来
                related_chunks = [c for c in chunks_with_nodes if node["id"] in c["nodes"]]
                for rc in related_chunks:
                    if rc not in final_chunks:
                        final_chunks.append(rc)

        return final_chunks


    def _find_by_similarity_improved(self, all_text: str, chunk: str, start_pos: int) -> int:
        """使用改进的相似度算法查找 chunk 位置"""
        import difflib
        
        # 扩大搜索范围
        search_range = min(max(len(chunk) * 3, 200), len(all_text) - start_pos)
        search_text = all_text[start_pos:start_pos + search_range]
        
        # 使用滑动窗口进行匹配
        chunk_len = len(chunk)
        best_match_pos = start_pos
        best_ratio = 0.0
        
        # 滑动窗口大小从chunk长度的50%到150%
        window_sizes = [int(chunk_len * 0.5), chunk_len, int(chunk_len * 1.5)]
        
        for window_size in window_sizes:
            if window_size <= 0:
                continue
                
            for i in range(len(search_text) - window_size + 1):
                window_text = search_text[i:i + window_size]
                
                # 计算相似度
                matcher = difflib.SequenceMatcher(None, chunk, window_text)
                ratio = matcher.ratio()
                
                # 如果相似度更高，更新最佳匹配
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_match_pos = start_pos + i
        
        # 提高相似度阈值到90%
        if best_ratio > 0.98:
            return best_match_pos
        
        # 如果相似度不够高，尝试基于字符的精确匹配
        return self._find_by_character_matching(all_text, chunk, start_pos)
    
    def _find_by_character_matching(self, all_text: str, chunk: str, start_pos: int) -> int:
        """基于字符的精确匹配"""
        search_range = min(max(len(chunk) * 2, 100), len(all_text) - start_pos)
        search_text = all_text[start_pos:start_pos + search_range]
        
        chunk_chars = list(chunk)
        search_chars = list(search_text)
        
        # 寻找最长公共子序列的起始位置
        max_match_len = 0
        best_pos = start_pos
        
        for i in range(len(search_chars) - len(chunk_chars) + 1):
            match_len = 0
            for j in range(min(len(chunk_chars), len(search_chars) - i)):
                if chunk_chars[j] == search_chars[i + j]:
                    match_len += 1
                else:
                    break
            
            if match_len > max_match_len:
                max_match_len = match_len
                best_pos = start_pos + i
        
        # 如果匹配长度超过chunk长度的70%，认为找到了
        if max_match_len > len(chunk) * 0.7:
            return best_pos
        
        # 最后兜底：返回开始位置
        return start_pos

    def generate_node_id(self) -> str:
        return str(uuid.uuid4())


    def _build_source_node_data(self, chunk_text: dict, node_map: dict) -> list[dict]:
        """构建源节点数据"""
        source_data = self._create_source_data_items(chunk_text, node_map)
        source_node = self._create_source_nodes(source_data, node_map)
        return source_node

    def _create_source_data_items(self, chunk_text: dict, node_map: dict) -> list[dict]:
        """创建源数据项"""
        source_data = []
        chunk_type = chunk_text["type"]

        for item_node in chunk_text["nodes"]:
            source_data_item = {
                "page": node_map[item_node]["page_idx"],
                "node_id": item_node,
                "ref_image_node": self._get_ref_image_node(chunk_type, item_node, node_map),
                "ref_table_node": self._get_ref_table_node(chunk_type, item_node, node_map),
            }
            source_data.append(source_data_item)

            # 检查是否有引用的图片或表格节点需要添加
            referenced_images = node_map[item_node].get('referenced_images', [])
            referenced_tables = node_map[item_node].get('referenced_tables', [])

            # 处理引用的图片节点
            if referenced_images:
                for ref_image_node in referenced_images:
                    # 检查source_data中是否已经存在该node_id
                    if not any(item["node_id"] == ref_image_node for item in source_data):
                        ref_image_item = {
                            "page": node_map[ref_image_node]["page_idx"],
                            "node_id": ref_image_node,
                            "ref_image_node": self._get_ref_image_node("chunk_image", ref_image_node, node_map),
                            "ref_table_node": self._get_ref_table_node("chunk_image", ref_image_node, node_map),
                        }
                        source_data.append(ref_image_item)

            # 处理引用的表格节点
            if referenced_tables:
                for ref_table_node in referenced_tables:
                    # 检查source_data中是否已经存在该node_id
                    if not any(item["node_id"] == ref_table_node for item in source_data):
                        ref_table_item = {
                            "page": node_map[ref_table_node]["page_idx"],
                            "node_id": ref_table_node,
                            "ref_image_node": self._get_ref_image_node("chunk_table", ref_table_node, node_map),
                            "ref_table_node": self._get_ref_table_node("chunk_table", ref_table_node, node_map),
                        }
                        source_data.append(ref_table_item)

        return source_data

    def _get_ref_image_node(self, chunk_type: str, item_node: str, node_map: dict) -> Union[bool, list]:
        """获取图片引用节点"""
        if chunk_type == "chunk_image":
            return True
        elif chunk_type == "chunk_table":
            return False
        return node_map[item_node]["referenced_images"]

    def _get_ref_table_node(self, chunk_type: str, item_node: str, node_map: dict) -> Union[bool, list]:
        """获取表格引用节点"""
        if chunk_type == "chunk_image":
            return False
        elif chunk_type == "chunk_table":
            return True
        return node_map[item_node]["referenced_tables"]

    def _create_source_nodes(self, source_data: list[dict], node_map: dict) -> list[dict]:
        """创建源节点"""
        source_node = []
        for source_data_node in source_data:
            node_id = source_data_node["node_id"]

            if node_map[node_id]["type"]=="table" or node_map[node_id]["type"]=="image":
                if type(node_map[node_id].get("caption",""))!=list and len(node_map[node_id].get("caption",[]))!=0:
                    text = node_map[node_id].get("caption", [""])[0]+node_map[node_id].get("text", "")
                else:
                    text = node_map[node_id].get("text", "")
            else:
                text=node_map[node_id].get("text", "")
            src_node = {
                "src_node_text": text,
                "src_node_bbox": node_map[node_id].get("bbox", []),
                "src_node_type": node_map[node_id]["type"],
                "src_node_id": node_map[node_id]["id"],
                "src_node_row": node_map[node_id].get("actual_row_idx", ""),
                "src_node_page": node_map[node_id]["page_idx"],
                "src_ref_image": source_data_node["ref_image_node"],
                "src_ref_table": source_data_node["ref_table_node"],
            }
            source_node.append(src_node)
        return source_node


    def _create_chunk(
        self,
        content: str,
        chunk_index: int,
        file_name: str = "",
        file_id: str = "",
        source_data: Optional[list[dict[str, Any]]] = None,
        chunk_split_type: Optional[str] = "",
        parent_node: Optional[list] ="",
        chunk_id: Optional[str] = "",
        ori_content: Optional[str] = None,
    ) -> Chunk:
        """创建Chunk对象"""
        metadata = ChunkMetadata(
            chunk_index=chunk_index,
            file_name=file_name,
            file_id=file_id,
            chunk_size=len(content),
            split_method=self.__class__.__name__,
            source_data=source_data or [],
            chunk_split_type=chunk_split_type,
            parent_node=parent_node,
            chunk_id=chunk_id
        )
        # 如果未传入 ori_content，则默认使用 content
        if ori_content is None:
            ori_content = content
        return Chunk(content=content, metadata=metadata, ori_content=ori_content)

    def group_by_page_idx(self,text):
        """
        将字典列表按 page_idx 分组，每组保留原始顺序。
        返回一个字典，键为 page_idx，值为该页的所有字典列表。
        """
        grouped = defaultdict(list)
        for item in text:
            grouped[item['page_idx']].append(item)
        return dict(grouped)

    def _merge_small_chunks(self, chunks: list[str], chunk_size: int) -> list[str]:
        """合并小于chunk_size的chunks"""
        if not chunks:
            return chunks

        merged_chunks = []
        i = 0

        while i < len(chunks):
            current_chunk = chunks[i]

            # 如果当前chunk长度已经超过chunk_size，直接添加
            if len(current_chunk) >= chunk_size:
                merged_chunks.append(current_chunk)
                i += 1
            else:
                # 尝试合并后续的chunks
                merged_chunk = current_chunk
                j = i + 1

                while j < len(chunks):
                    next_chunk = chunks[j]
                    # 检查合并后是否超过chunk_size
                    if len(merged_chunk + next_chunk) <= chunk_size:
                        merged_chunk += next_chunk
                        j += 1
                    else:
                        break

                merged_chunks.append(merged_chunk)
                i = j

        return merged_chunks

    def _force_split_large_chunks(self, chunks: list[str], chunk_size: int) -> list[str]:
        """
        保底逻辑：强制分割超过chunk_size的chunks
        对于chunks中的每一项而言，存在超过chunk_size的数据，则强制将该项分为不超过chunk_size的大小，
        超过的部分需要紧跟着该项
        
        Args:
            chunks: 原始chunks列表
            chunk_size: 最大chunk大小
            
        Returns:
            处理后的chunks列表
        """
        if not chunks:
            return chunks
            
        result_chunks = []
        
        for chunk in chunks:
            if len(chunk) <= chunk_size:
                # 如果chunk大小不超过限制，直接添加
                result_chunks.append(chunk)
            else:
                # 如果chunk超过限制，强制分割
                start = 0
                while start < len(chunk):
                    # 取不超过chunk_size的部分
                    end = start + chunk_size
                    if end > len(chunk):
                        end = len(chunk)
                    
                    # 添加当前分割的部分
                    result_chunks.append(chunk[start:end])
                    start = end
        
        return result_chunks
class StrictSeparatorSplitter(TextSplitter):
    """
    严格按照给定分隔符分割，每个分隔段直接作为一个 chunk 返回（不再做合并）。

    该分割器不同于标准的langchain分割器，它不会将小的分割段合并成
    满足chunk_size要求的chunk，而是严格按分隔符分割，每个分割段
    直接作为一个独立的chunk返回。

    参数:
      separator: 字面或正则（由 is_separator_regex 决定）
      is_separator_regex: True 表示 separator 是正则
      keep_separator: 是否在每个 chunk 末尾保留分隔符（只支持简单的 'end' 语义）
      strip_whitespace: 是否对每个 chunk 做 strip()
    """

    def __init__(
        self,
        separator: str = "\n\n",
        is_separator_regex: bool = False,
        keep_separator: bool = False,
        strip_whitespace: bool = True,
        **kwargs,
    ):
        # 我们不依赖父类的 chunk_size 合并逻辑，所以 chunk_size/overlap 可随意
        super().__init__(**kwargs)
        self._separator = separator
        self._is_regex = is_separator_regex
        self._keep_sep = keep_separator
        self._strip = strip_whitespace

    def split_text(self, text: str) -> list[str]:
        """
        按照分隔符严格分割文本

        Args:
            text: 要分割的文本

        Returns:
            分割后的文本列表
        """
        if self._separator == "":
            # 退化到按字符分割
            splits = list(text)
        else:
            pattern = self._separator if self._is_regex else re.escape(self._separator)
            if self._keep_sep:
                # 用捕获组把分隔符保留在结果里，然后把内容+分隔符合并成一个片段（末尾保留 sep）
                parts = re.split(f"({pattern})", text)
                chunks = []
                i = 0
                # parts 的形式通常是: [pre, sep, mid, sep, ... , tail]
                while i < len(parts):
                    if i + 1 < len(parts):
                        chunks.append(parts[i] + parts[i + 1])
                        i += 2
                    else:
                        chunks.append(parts[i])
                        i += 1
                splits = chunks
            else:
                # 直接按分隔符切（分隔符不保留）
                splits = re.split(pattern, text)

        if self._strip:
            splits = [s.strip() for s in splits]
        # 去掉空片段
        return [s for s in splits if s != ""]


class CharacterSplitter(BaseSplitter):
    """字符分割器"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50, separator: str = "\n", **kwargs):
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        self.separator = separator
        self.chunk_type = kwargs.get("chunk_type", None)
        self.sub_chunk_size = kwargs.get("sub_chunk_size", None)
        self.sub_separator = kwargs.get("sub_separator", None)
        use_force_separator = kwargs.get("use_force_separator", False)
        if use_force_separator:
            # 强制分隔符模式：严格按照分隔符分割，不做合并
            self._langchain_splitter = StrictSeparatorSplitter(
                separator=separator, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )
        else:
            # 标准模式：根据chunk_size智能合并分割段
            self._langchain_splitter = CharacterTextSplitter(
                separator=separator, chunk_size=chunk_size, chunk_overlap=chunk_overlap
            )

    def split(
        self, text: list, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ):
        """使用字符分割器分割文本"""
        try:
            if not isinstance(text, list):
                return []
            results=[]
            # 使用第二种切分方案：基于去除换行符、空格符和分隔符的文本
            all_text, all_text2, spans_node = self.split_v1_v2(text, self.separator)
            chunks = self._langchain_splitter.split_text(all_text)
            results = self.split_v2_v2(all_text2, spans_node, chunks, text, self.chunk_overlap, True, self.separator)

            node_map = {item["id"]: item for item in text}
            all_chunks = []

            for i, chunk_text in enumerate(results):
                source_node = self._build_source_node_data(chunk_text, node_map)
                chunk = self._create_chunk(
                    content=chunk_text["content"],
                    chunk_index=i+1,
                    file_name=file_name,
                    file_id=file_id,
                    source_data=source_node,
                    chunk_split_type="tradition",
                    parent_node=[],
                    chunk_id=self.generate_node_id()
                )
                all_chunks.append(chunk)

            return all_chunks

        except Exception as e:
            logger.exception(f"字符分割失败: {str(traceback.format_exc())}")
            raise


class RecursiveCharacterSplitter(BaseSplitter):
    """递归字符分割器"""

    def __init__(
        self, chunk_size: int = 500, chunk_overlap: int = 50, separators: Optional[list[str]] = None, **kwargs
    ):
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        if len(separators) != 0 and isinstance(separators, list):
            self.separators = separators + ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        else:
            self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        # self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，"]
        self.chunk_type = kwargs.get("chunk_type", None)
        self.sub_chunk_size = kwargs.get("sub_chunk_size", None)
        self.sub_separator = kwargs.get("sub_separator", None)
        self._langchain_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=self.separators, length_function=len
        )

    def split(
        self, text: dict, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ):
        """使用递归字符分割器分割文本"""
        try:
            if isinstance(text, list):
                results=[]
                # 使用第二种切分方案：基于去除换行符、空格符和分隔符的文本
                all_text, all_text2, spans_node = self.split_v1_v2(text, self.separators)
                chunks = self._langchain_splitter.split_text(all_text)
                results = self.split_v2_v2(all_text2, spans_node, chunks, text, self.chunk_overlap, True, self.separators)
                
                node_map = {item["id"]: item for item in text}
                all_chunks = []

                for i, chunk_text in enumerate(results):
                    source_node = self._build_source_node_data(chunk_text, node_map)
                    chunk = self._create_chunk(
                        content=chunk_text["content"],
                        chunk_index=i+1,
                        file_name=file_name,
                        file_id=file_id,
                        source_data=source_node,
                        chunk_split_type="tradition",
                        parent_node=[],
                        chunk_id=self.generate_node_id()
                    )
                    all_chunks.append(chunk)

                return all_chunks

        except Exception as e:
            logger.exception(f"递归字符分割失败: {str(traceback.format_exc())}")
            raise


class SpacySplitter(BaseSplitter):
    """Spacy分割器"""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separator: str = "\n",
        pipeline: str = "zh_core_web_sm",
        **kwargs,
    ):
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        self.separator = separator
        self.pipeline = pipeline
        self.chunk_type = kwargs.get("chunk_type", None)
        self.sub_chunk_size = kwargs.get("sub_chunk_size", None)
        self.sub_separator = kwargs.get("sub_separator", None)
        self._langchain_splitter = SpacyTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separator=separator, pipeline=pipeline
        )

    def split(
        self, text: dict, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ):
        """使用Spacy分割器分割文本"""
        try:
            if isinstance(text, list):
                results=[]
                # 使用第二种切分方案：基于去除换行符、空格符和分隔符的文本
                all_text, all_text2, spans_node = self.split_v1_v2(text, self.separator)
                chunks = self._langchain_splitter.split_text(all_text)
                results = self.split_v2_v2(all_text2, spans_node, chunks, text, self.chunk_overlap, True, self.separator)


                node_map = {item["id"]: item for item in text}
                all_chunks = []

                for i, chunk_text in enumerate(results):
                    source_node = self._build_source_node_data(chunk_text, node_map)
                    chunk = self._create_chunk(
                        content=chunk_text["content"],
                        chunk_index=i+1,
                        file_name=file_name,
                        file_id=file_id,
                        source_data=source_node,
                        chunk_split_type="tradition",
                        parent_node=[],
                        chunk_id=self.generate_node_id()
                    )
                    all_chunks.append(chunk)

                return all_chunks

        except Exception as e:
            logger.exception(f"Spacy分割失败: {str(traceback.format_exc())}")
            raise

class parent_by_page(BaseSplitter):
    """递归字符分割器"""

    def __init__(
            self, chunk_size: int = 500, chunk_overlap: int = 50, separators: Optional[list[str]] = None, **kwargs
    ):
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        if len(separators) != 0 and isinstance(separators, list):
            self.separators = separators + ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        else:
            self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        # self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，"]
        self.chunk_type = kwargs.get("chunk_type", None)
        self.sub_chunk_size = kwargs.get("sub_chunk_size", None)
        self.sub_separator = kwargs.get("sub_separator", None)
        self._langchain_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=self.separators, length_function=len
        )

    def _convert_to_source_node_format(self, ori_result: list[dict], node_map: dict) -> list[dict]:
        """将原始数据转换为_build_source_node_data的返回格式"""
        source_nodes = []
        for item in ori_result:
            node_id = item["id"]
            
            # 处理文本内容
            if node_map[node_id]["type"] == "table" or node_map[node_id]["type"] == "image":
                if type(node_map[node_id].get("caption", "")) != list and len(node_map[node_id].get("caption", [])) != 0:
                    text = node_map[node_id].get("caption", [""])[0] + node_map[node_id].get("text", "")
                else:
                    text = node_map[node_id].get("text", "")
            else:
                text = node_map[node_id].get("text", "")
            
            # 处理引用关系
            if item["type"] == "image":
                ref_image = True
                ref_table = False
            elif item["type"] == "table":
                ref_image = False
                ref_table = True
            else:
                ref_image = item.get("referenced_images", [])
                ref_table = item.get("referenced_tables", [])
            
            src_node = {
                "src_node_text": text,
                "src_node_bbox": node_map[node_id].get("bbox", []),
                "src_node_type": node_map[node_id]["type"],
                "src_node_id": node_map[node_id]["id"],
                "src_node_row": node_map[node_id].get("actual_row_idx", ""),
                "src_node_page": node_map[node_id]["page_idx"],
                "src_ref_image": ref_image,
                "src_ref_table": ref_table,
            }
            source_nodes.append(src_node)
        
        return source_nodes

    def split(
            self, text: dict, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ):
        """使用递归字符分割器分割文本"""
        try:
            # 子块splitter分割器实例类
            if  isinstance(self.sub_separator, list) and len(self.sub_separator) != 0:
                self.sub_separator = self.sub_separator + ["\n\n", "\n", "。", "！", "？", "；", "，", ",", " ", ""]
            else:
                self.sub_separator = ["\n\n", "\n", "。", "！", "？", "；", "，", ",", " ", ""]
            child_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.sub_chunk_size,
                    chunk_overlap=0,
                    separators=self.sub_separator,
                    length_function=len
                )
            node_map = {item["id"]: item for item in text}
            all_chunks=[]
            all_texts=self.group_by_page_idx(text)
            parent_index=0
            last_parent_chunk_obj = None
            last_parent_last_node_id = None
            # 存储待添加到后续父块的子块信息
            pending_child_chunks = []
            for idx,text in enumerate(all_texts.values()):
                #按页作为父块
                if isinstance(text, list):
                    # 使用第二种切分方案：基于去除换行符、空格符和分隔符的文本
                    all_text, all_text2, spans_node = self.split_v1_v2(text, self.separators)
                    #先对父块进行切分
                    chunks = self._langchain_splitter.split_text(all_text)
                    # 合并小于chunk_size的chunks
                    chunks = self._merge_small_chunks(chunks, self.chunk_size)
                    # 保底逻辑：强制分割超过chunk_size的chunks
                    # chunks = self._force_split_large_chunks(chunks, self.chunk_size)

                    last_chunk=False
                    if chunks==[] and all_text=="":
                        # 如果是页面中只有图片/表格等非文本节点的情况下的特殊处理
                        child_index=0
                        parent_chunk_id = self.generate_node_id()
                        parent_reference_chunk = []

                        ori_result=text[0]
                        if last_parent_chunk_obj and last_parent_last_node_id:
                            curr_first_id = ori_result["id"] if ori_result else None
                            # 仅当上一父块最后节点与当前父块第一个节点处于同一页时，才进行跨父块缺失节点补齐

                            # 使用 node_map 的顺序来定位间隔节点
                            ordered_nodes = list(node_map.values())
                            id_to_index = {n.get("id"): i for i, n in enumerate(ordered_nodes)}
                            prev_idx = id_to_index.get(last_parent_last_node_id)
                            curr_idx = id_to_index.get(curr_first_id)
                            if prev_idx is not None and curr_idx is not None and prev_idx + 1 < curr_idx:
                                gap_items = ordered_nodes[prev_idx + 1: curr_idx]
                                additional_content_parts = []
                                for gap_item in gap_items:
                                    if gap_item.get("type") in ["image", "table"] and gap_item.get("text", ""):
                                        # 检查是否被引用
                                        is_ref = False
                                        for other_item in node_map.values():
                                            if (gap_item["id"] in other_item.get("referenced_images", []) or
                                                    gap_item["id"] in other_item.get("referenced_tables", [])):
                                                is_ref = True
                                                break
                                        new_parent = False
                                        if not is_ref:
                                            for teemp in text:
                                                if teemp["id"] == gap_item["id"]:
                                                    new_parent = True
                                                    break
                                            if new_parent == True:
                                                # 创建子块并存储到待添加列表中，等待后续父块创建时添加
                                                gap_child_id = self.generate_node_id()
                                                gap_source = self._build_source_node_data(
                                                    {"type": f"chunk_{gap_item['type']}", "content": gap_item["text"],
                                                     "nodes": [gap_item["id"]]},
                                                    node_map
                                                )
                                                gap_child = self._create_chunk(
                                                    content=gap_item["text"],
                                                    chunk_index=0,  # 临时索引，后续会更新
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=gap_source,
                                                    chunk_split_type="child",
                                                    parent_node=[],  # 临时为空，后续会更新
                                                    chunk_id=gap_child_id
                                                )
                                                # 存储待添加的子块信息
                                                pending_child_chunks.append({
                                                    'child_chunk': gap_child,
                                                    'source_data': gap_source,
                                                    'content': gap_item["text"]
                                                })


                                            else:
                                                # 创建子块
                                                gap_child_id = self.generate_node_id()
                                                gap_source = self._build_source_node_data(
                                                    {"type": f"chunk_{gap_item['type']}", "content": gap_item["text"],
                                                     "nodes": [gap_item["id"]]},
                                                    node_map
                                                )
                                                gap_child = self._create_chunk(
                                                    content=gap_item["text"],
                                                    chunk_index=len(last_parent_chunk_obj.metadata.parent_node) + 1,
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=gap_source,
                                                    chunk_split_type="child",
                                                    parent_node=[last_parent_chunk_obj.metadata.chunk_id],
                                                    chunk_id=gap_child_id
                                                )
                                                all_chunks.append(gap_child)
                                                last_parent_chunk_obj.metadata.parent_node.append(gap_child_id)
                                                additional_content_parts.append(gap_item["text"])
                                                # 同步源数据到父块
                                                last_parent_chunk_obj.metadata.source_data.extend(gap_source)
                                if additional_content_parts:
                                    # 将缺失图片描述追加到上一个父块内容末尾
                                    last_parent_chunk_obj.content += "\n" + "\n".join(additional_content_parts)
                        # 为非文本节点创建父子块
                        for item in text:
                            if item["type"] in ["image", "table"]:
                                # 检查节点是否被引用
                                is_referenced = False
                                for other_item in text:
                                    if (item["id"] in other_item.get("referenced_images", []) or
                                        item["id"] in other_item.get("referenced_tables", [])):
                                        is_referenced = True
                                        break

                                # 只有未被引用的节点才创建块
                                if not is_referenced and item.get("text", "") != "":
                                    child_chunk_id = self.generate_node_id()
                                    parent_reference_chunk.append(child_chunk_id)

                                    # 创建子块
                                    source_node = self._build_source_node_data(
                                        {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]},
                                        node_map
                                    )
                                    child_index += 1
                                    child_chunk = self._create_chunk(
                                        content=item["text"],
                                        chunk_index=child_index,
                                        file_name=file_name,
                                        file_id=file_id,
                                        source_data=source_node,
                                        chunk_split_type="child",
                                        parent_node=[parent_chunk_id],
                                        chunk_id=child_chunk_id
                                    )
                                    all_chunks.append(child_chunk)

                        # 如果有子块，创建父块
                        if parent_reference_chunk:
                            # 创建父块内容（所有非文本节点的文本）
                            parent_content = ""
                            for item in text:
                                if item["type"] in ["image", "table"] and item.get("text", "") != "":
                                    parent_content += item["text"] + "\n"

                            # 创建父块的源数据
                            parent_source_nodes = []
                            for item in text:
                                if item["type"] in ["image", "table"] and item.get("text", "") != "":
                                    parent_source_nodes.extend(self._build_source_node_data(
                                        {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]},
                                        node_map
                                    ))
                            parent_index += 1
                            parent_chunk = self._create_chunk(
                                content=parent_content.strip(),
                                chunk_index=parent_index,
                                file_name=file_name,
                                file_id=file_id,
                                source_data=parent_source_nodes,
                                chunk_split_type="parent",
                                parent_node=parent_reference_chunk,
                                chunk_id=parent_chunk_id
                            )
                            all_chunks.append(parent_chunk)
                            last_chunk=True
                    else:
                        # 正常的父块处理逻辑
                        temp=-1
                        for chunk in chunks:
                            # 每一个chunk是一个父块
                            child_index = 0
                            # 找到当前chunk对应的节点列表
                            parent_reference_chunk = []
                            parent_chunk_id = self.generate_node_id()
                            parent_chunk=[chunk]
                            parent_results= self.split_v2_v2(all_text2, spans_node, parent_chunk, text, self.chunk_overlap, False, self.separators)
                            pure_text = [item for item in text]
                            if parent_results!=[]:
                                first_id = parent_results[0]["nodes"][0]
                                last_id = parent_results[0]["nodes"][-1]
                                idx_map = {n['id']: i for i, n in enumerate(pure_text)}
                                start = idx_map.get(first_id)
                                if temp+2<=start and len(text)==1:
                                    # 这种特殊情况下，temp+2到start之间的所有元素都单独成为一块
                                    for idx in range(temp+1, start):
                                        if pure_text[idx]["type"] in ["image", "table"]:
                                            # 检查节点是否被引用
                                            is_referenced = False
                                            for other_item in text:
                                                if (pure_text[idx]["id"] in other_item.get("referenced_images", []) or
                                                        pure_text[idx]["id"] in other_item.get("referenced_tables", [])):
                                                    is_referenced = True
                                                    break

                                            # 只有未被引用的节点才创建块
                                            if not is_referenced:
                                                limp_child_chunk_id = self.generate_node_id()
                                                limp_parent_chunk_id = self.generate_node_id()
                                                limp_parent_reference_chunk=[limp_child_chunk_id]

                                                # 创建子块
                                                source_node = self._build_source_node_data(
                                                    {"type": f"chunk_{pure_text[idx]['type']}", "content": pure_text[idx]["text"],
                                                     "nodes": [pure_text[idx]["id"]]},
                                                    node_map
                                                )
                                                child_index+=1
                                                limp_pic = self._create_chunk(
                                                    content=pure_text[idx]["text"],
                                                    chunk_index=child_index,
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=source_node,
                                                    chunk_split_type="child",
                                                    parent_node=[limp_parent_chunk_id],
                                                    chunk_id=limp_child_chunk_id
                                                )
                                                all_chunks.append(limp_pic)
                                                parent_index += 1
                                                limp_pic2 = self._create_chunk(
                                                    content=pure_text[idx]["text"],
                                                    chunk_index=parent_index,
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=source_node,
                                                    chunk_split_type="parent",
                                                    parent_node=limp_parent_reference_chunk,
                                                    chunk_id=limp_parent_chunk_id
                                                )
                                                all_chunks.append(limp_pic2)
                                                parent_index +=1
                                    # 中间的单独成一个子块
                                end = idx_map.get(last_id)
                                if start is None or end is None:
                                    raise ValueError('result 首尾 id 在 pure_text 中不存在')
                                temp=end

                                # 3. 取出闭区间 [start, end] 所有元素，并添加后续连续的图片
                                ori_result = pure_text[start: end + 1]
                            else:
                                ori_result=[]

                            sub_chunk = child_splitter.split_text(chunk)
                            results = self.split_v2_v2(all_text2, spans_node, sub_chunk, ori_result, self.chunk_overlap, True,
                                                       self.separators)
                            # 父块之间缺失的图片/表格补齐：
                            # 如果存在上一个父块，且上一个父块最后节点 与 当前父块第一个节点 在整页序列中不相邻，
                            # 则将中间连续的未被引用的图片/表格节点追加到上一个父块下
                            gap_parent_id=False
                            if last_parent_chunk_obj and last_parent_last_node_id:
                                curr_first_id = ori_result[0]["id"] if ori_result else None
                                # 仅当上一父块最后节点与当前父块第一个节点处于同一页时，才进行跨父块缺失节点补齐

                                # 使用 node_map 的顺序来定位间隔节点
                                ordered_nodes = list(node_map.values())
                                id_to_index = {n.get("id"): i for i, n in enumerate(ordered_nodes)}
                                prev_idx = id_to_index.get(last_parent_last_node_id)
                                curr_idx = id_to_index.get(curr_first_id)
                                if prev_idx is not None and curr_idx is not None and prev_idx + 1 < curr_idx :
                                    gap_items = ordered_nodes[prev_idx + 1: curr_idx]
                                    additional_content_parts = []
                                    for gap_item in gap_items:
                                        if gap_item.get("type") in ["image", "table"] and gap_item.get("text", ""):
                                            # 检查是否被引用
                                            is_ref = False
                                            for other_item in node_map.values():
                                                if (gap_item["id"] in other_item.get("referenced_images", []) or
                                                    gap_item["id"] in other_item.get("referenced_tables", [])):
                                                    is_ref = True
                                                    break
                                            new_parent=False
                                            if not is_ref:
                                                for teemp in text:
                                                    if teemp["id"]==gap_item["id"]:
                                                        new_parent=True
                                                        break
                                                if new_parent==True:
                                                    # 创建子块并存储到待添加列表中，等待后续父块创建时添加
                                                    gap_child_id = self.generate_node_id()
                                                    gap_source = self._build_source_node_data(
                                                        {"type": f"chunk_{gap_item['type']}", "content": gap_item["text"], "nodes": [gap_item["id"]]},
                                                        node_map
                                                    )
                                                    gap_child = self._create_chunk(
                                                        content=gap_item["text"],
                                                        chunk_index=0,  # 临时索引，后续会更新
                                                        file_name=file_name,
                                                        file_id=file_id,
                                                        source_data=gap_source,
                                                        chunk_split_type="child",
                                                        parent_node=[],  # 临时为空，后续会更新
                                                        chunk_id=gap_child_id
                                                    )
                                                    # 存储待添加的子块信息
                                                    pending_child_chunks.append({
                                                        'child_chunk': gap_child,
                                                        'source_data': gap_source,
                                                        'content': gap_item["text"]
                                                    })
                                                    

                                                else:
                                                    # 创建子块
                                                    gap_child_id = self.generate_node_id()
                                                    gap_source = self._build_source_node_data(
                                                        {"type": f"chunk_{gap_item['type']}", "content": gap_item["text"], "nodes": [gap_item["id"]]},
                                                        node_map
                                                    )
                                                    gap_child = self._create_chunk(
                                                        content=gap_item["text"],
                                                        chunk_index=len(last_parent_chunk_obj.metadata.parent_node) + 1,
                                                        file_name=file_name,
                                                        file_id=file_id,
                                                        source_data=gap_source,
                                                        chunk_split_type="child",
                                                        parent_node=[last_parent_chunk_obj.metadata.chunk_id],
                                                        chunk_id=gap_child_id
                                                    )
                                                    all_chunks.append(gap_child)
                                                    last_parent_chunk_obj.metadata.parent_node.append(gap_child_id)
                                                    additional_content_parts.append(gap_item["text"])
                                                    # 同步源数据到父块
                                                    last_parent_chunk_obj.metadata.source_data.extend(gap_source)
                                    if additional_content_parts:
                                        # 将缺失图片描述追加到上一个父块内容末尾
                                        last_parent_chunk_obj.content += "\n" + "\n".join(additional_content_parts)


                            # 添加子块
                            
                            # 计算待添加子块的数量，用于调整后续子块的索引
                            pending_count = len(pending_child_chunks) if pending_child_chunks else 0
                            
                            # 为父块创建阶段暂存待添加子块的内容与源数据
                            pending_content_parts_buffer = []
                            pending_source_nodes_buffer = []
                            
                            # 首先处理待添加的子块（放在前面）
                            if pending_child_chunks:
                                for i, pending_item in enumerate(pending_child_chunks):
                                    child_chunk = pending_item['child_chunk']
                                    # 更新子块的父节点引用和索引（前n个）
                                    child_chunk.metadata.parent_node = [parent_chunk_id]
                                    child_chunk.metadata.chunk_index = i + 1
                                    # 添加到父块的子块引用列表
                                    parent_reference_chunk.append(child_chunk.metadata.chunk_id)
                                    # 添加到所有块列表
                                    all_chunks.append(child_chunk)
                                    # 收集子块内容与源数据，延后在父块创建时统一写入
                                    pending_content_parts_buffer.append(pending_item['content'])
                                    pending_source_nodes_buffer.extend(pending_item['source_data'])
                                # 清空待添加列表（已转为正式子块并暂存其内容与源数据）
                                pending_child_chunks = []
                            
                            for i, chunk_text in enumerate(results):
                                child_chunk_id=self.generate_node_id()
                                parent_reference_chunk.append(child_chunk_id)
                                source_node = self._build_source_node_data(chunk_text, node_map)
                                child_index += 1
                                chunk = self._create_chunk(
                                    content=chunk_text["content"],
                                    chunk_index=child_index + pending_count,
                                    file_name=file_name,
                                    file_id=file_id,
                                    source_data=source_node,
                                    chunk_split_type="child",
                                    parent_node=[parent_chunk_id],
                                    chunk_id=child_chunk_id
                                )
                                all_chunks.append(chunk)
                                # 此处不更新 last_parent_*，应在创建父块后统一更新，
                                # 以确保“父块之间缺失节点补齐”逻辑能够正确挂载到上一父块

                            # 检查是否存在未处理的图片/表格节点，让它们单独成为子块
                            processed_node_ids = set()
                            for chunk_text in results:
                                processed_node_ids.update(chunk_text["nodes"])

                            # 使用原始的text参数来检查未处理的图片/表格节点
                            for item in ori_result:
                                if (item["type"] in ["image", "table"] and
                                    item["id"] not in processed_node_ids and
                                    item.get("text", "") != ""):
                                    # 检查节点是否被引用
                                    is_referenced = False
                                    for other_item in text:
                                        if (item["id"] in other_item.get("referenced_images", []) or
                                            item["id"] in other_item.get("referenced_tables", [])):
                                            is_referenced = True
                                            break

                                    # 只有未被引用的节点才创建块
                                    if not is_referenced:
                                        child_chunk_id = self.generate_node_id()
                                        parent_reference_chunk.append(child_chunk_id)

                                        # 创建子块
                                        source_node = self._build_source_node_data(
                                            {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]},
                                            node_map
                                        )
                                        child_index+=1
                                        chunk = self._create_chunk(
                                            content=item["text"],
                                            chunk_index=child_index + pending_count,
                                            file_name=file_name,
                                            file_id=file_id,
                                            source_data=source_node,
                                            chunk_split_type="child",
                                            parent_node=[parent_chunk_id],
                                            chunk_id=child_chunk_id
                                        )
                                        all_chunks.append(chunk)

                            # 添加父块
                            for i, chunk_text in enumerate(parent_results):
                                # 获取原始父块的源数据
                                source_node = self._build_source_node_data(chunk_text, node_map)

                                # 添加未处理图片/表格节点的源数据
                                for item in text:
                                    if (item["type"] in ["image", "table"] and
                                        item["id"] not in processed_node_ids and
                                        item.get("text", "") != ""):
                                        # 检查节点是否被引用
                                        is_referenced = False
                                        for other_item in text:
                                            if (item["id"] in other_item.get("referenced_images", []) or
                                                item["id"] in other_item.get("referenced_tables", [])):
                                                is_referenced = True
                                                break

                                        # 只有未被引用的节点才添加到父块的源数据中
                                        if not is_referenced:
                                            additional_source_node = self._build_source_node_data(
                                                {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]},
                                                node_map
                                            )
                                            source_node.extend(additional_source_node)

                                # 获取已处理的节点ID集合
                                processed_node_ids = set()
                                for chunk_text_item in results:
                                    if chunk_text_item["type"]=="chunk_text":
                                        processed_node_ids.update(chunk_text_item["nodes"])

                                # 构建完整的父块内容，以chunk为基础，按ori_result顺序插入未挂载图片
                                parent_content = chunk_text["content"]

                                # 找到未挂载的图片/表格节点，按ori_result顺序插入到正确位置
                                unmounted_items = []
                                is_referenced = False
                                for item in ori_result:
                                    if (item["type"] in ["image", "table"] and
                                        item["id"] not in processed_node_ids and
                                        item.get("text", "") != ""):
                                        # 检查节点是否被引用
                                        is_referenced = False
                                        for other_item in ori_result:
                                            if (item["id"] in other_item.get("referenced_images", []) or
                                                item["id"] in other_item.get("referenced_tables", [])):
                                                is_referenced = True
                                                break

                                        # 只有未被引用的节点才需要插入
                                        if not is_referenced:
                                            unmounted_items.append(item)

                                # 如果有未挂载的图片，需要重新构建内容以保持正确顺序
                                if unmounted_items:
                                    # 按ori_result顺序重新构建内容
                                    content_parts = []

                                    # 将chunk_text["content"]按行分割
                                    chunk_lines = chunk_text["content"].split('\n')

                                    # 按ori_result顺序构建内容
                                    chunk_line_idx = 0
                                    for item in ori_result:
                                        if item["id"] in processed_node_ids and item["type"] == "text":
                                            # 对于已处理的文本节点，使用chunk_lines中的内容
                                            if chunk_line_idx < len(chunk_lines):
                                                content_parts.append(chunk_lines[chunk_line_idx])
                                                chunk_line_idx += 1
                                        elif item in unmounted_items:
                                            # 对于未挂载的图片/表格节点
                                            content_parts.append(item["text"])

                                    # 如果还有剩余的chunk_lines，添加到末尾
                                    while chunk_line_idx < len(chunk_lines):
                                        content_parts.append(chunk_lines[chunk_line_idx])
                                        chunk_line_idx += 1

                                    # 合并所有内容部分
                                    parent_content = '\n'.join(content_parts)

                                # 在转换为 source_node 之前，补充 ori_result 中被文本引用的图片/表格节点，避免重复
                                expanded_result = []
                                try:
                                    existing_ids = set([n.get("id") for n in ori_result])

                                    for base_item in ori_result:
                                        expanded_result.append(base_item)
                                        # 仅当当前为文本节点时，处理引用的图片/表格
                                        if base_item.get("type") == "text":
                                            for ref_img_id in base_item.get("referenced_images", []) or []:
                                                ref_node = node_map.get(ref_img_id)
                                                if ref_node and ref_node.get("id") not in existing_ids:
                                                    expanded_result.append(ref_node)
                                                    existing_ids.add(ref_node.get("id"))
                                            for ref_tbl_id in base_item.get("referenced_tables", []) or []:
                                                ref_node = node_map.get(ref_tbl_id)
                                                if ref_node and ref_node.get("id") not in existing_ids:
                                                    expanded_result.append(ref_node)
                                                    existing_ids.add(ref_node.get("id"))
                                    # ori_result = expanded_result
                                except Exception:
                                    # 保底：若补充失败，不影响后续逻辑
                                    pass
                                # 将ori_result转换为source_node格式
                                source_node_data = self._convert_to_source_node_format(expanded_result, node_map)

                                if  is_referenced:
                                    parent_content=chunk_text["content"]
                                
                                # 在创建父块前，将待添加子块内容置前，并合并其源数据
                                if pending_content_parts_buffer:
                                    parent_content = "\n".join(pending_content_parts_buffer) + "\n" + parent_content
                                if pending_source_nodes_buffer:
                                    source_node_data.extend(pending_source_nodes_buffer)
                                # 使用后就地清空缓冲，避免影响后续父块
                                pending_content_parts_buffer = []
                                pending_source_nodes_buffer = []
                                
                                parent_index += 1
                                chunk = self._create_chunk(
                                    content=parent_content,
                                    chunk_index=parent_index,
                                    file_name=file_name,
                                    file_id=file_id,
                                    source_data=source_node_data,
                                    chunk_split_type="parent",
                                    parent_node=parent_reference_chunk,
                                    chunk_id=parent_chunk_id
                                )
                                all_chunks.append(chunk)
                                # 记录当前父块，用于下一父块进行跨父块缺失节点补齐判断
                                try:
                                    if ori_result:
                                        last_parent_last_node_id = ori_result[-1]["id"]
                                    last_parent_chunk_obj = chunk
                                except Exception:
                                    pass

            # 处理最后的未挂载图片/表格节点
            if all_chunks and not last_chunk:
                # 找到最后一个父块
                last_parent_chunk = None
                for chunk in reversed(all_chunks):
                    if chunk.metadata.chunk_split_type == "parent":
                        last_parent_chunk = chunk
                        break
                
                if last_parent_chunk:
                    # 检查输入text的最后若干项是否为未挂载的图片/表格节点
                    trailing_unmounted_items = []
                    for i in range(len(text) - 1, -1, -1):
                        item = text[i]
                        if item["type"] in ["image", "table"] and item.get("text", "") != "":
                            # 检查节点是否被引用
                            is_referenced = False
                            for other_item in text:
                                if (item["id"] in other_item.get("referenced_images", []) or 
                                    item["id"] in other_item.get("referenced_tables", [])):
                                    is_referenced = True
                                    break
                            
                            # 只有未被引用的节点才需要处理
                            if not is_referenced:
                                trailing_unmounted_items.insert(0, item)  # 保持原始顺序
                            else:
                                break
                        else:
                            break
                    
                    # 如果有未挂载的图片/表格节点，将它们作为最后一个父块的子块
                    if trailing_unmounted_items:
                        # 为每个未挂载的图片/表格节点创建子块
                        for item in trailing_unmounted_items:
                            child_chunk_id = self.generate_node_id()
                            
                            # 创建子块
                            source_node = self._build_source_node_data(
                                {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]}, 
                                node_map
                            )
                            
                            child_chunk = self._create_chunk(
                                content=item["text"],
                                chunk_index=len(last_parent_chunk.metadata.parent_node) + 1,
                                file_name=file_name,
                                file_id=file_id,
                                source_data=source_node,
                                chunk_split_type="child",
                                parent_node=[last_parent_chunk.metadata.chunk_id],
                                chunk_id=child_chunk_id
                            )
                            all_chunks.append(child_chunk)
                            
                            # 更新父块的parent_node列表
                            last_parent_chunk.metadata.parent_node.append(child_chunk_id)
                        
                        # 更新最后一个父块的内容，添加未挂载图片的描述
                        additional_content = []
                        for item in trailing_unmounted_items:
                            additional_content.append(item["text"])
                        
                        if additional_content:
                            # 将未挂载图片的描述添加到父块内容的末尾
                            last_parent_chunk.content += "\n" + "\n".join(additional_content)
                            
                            # 更新父块的源数据
                            for item in trailing_unmounted_items:
                                additional_source_node = self._build_source_node_data(
                                    {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]}, 
                                    node_map
                                )
                                last_parent_chunk.metadata.source_data.extend(additional_source_node)

            return all_chunks

        except Exception as e:
            logger.exception(f"递归字符分割失败: {str(traceback.format_exc())}")
            raise

class parent_by_paragraph(BaseSplitter):
    """递归字符分割器"""

    def __init__(
            self, chunk_size: int = 500, chunk_overlap: int = 50, separators: Optional[list[str]] = None, **kwargs
    ):
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        if len(separators) != 0 and isinstance(separators, list):
            self.separators = separators + ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        else:
            self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        # self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，",""]
        self.chunk_type = kwargs.get("chunk_type", None)
        self.sub_chunk_size = kwargs.get("sub_chunk_size", None)
        self.sub_separator = kwargs.get("sub_separator", None)
        self._langchain_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=self.separators, length_function=len
        )

    def _create_simple_node_source_data(self, node_id: str, node_map: dict, node_type: str) -> list[dict]:
        """为简单节点（image/table）创建源数据"""
        return [{
            "src_node_text": node_map[node_id].get("text", ""),
            "src_node_bbox": node_map[node_id].get("bbox", []),
            "src_node_type": node_map[node_id]["type"],
            "src_node_id": node_map[node_id]["id"],
            "src_node_row": node_map[node_id].get("actual_row_idx", ""),
            "src_node_page": node_map[node_id]["page_idx"],
            "src_ref_image": True if node_type == "image" else False,
            "src_ref_table": True if node_type == "table" else False,
        }]

    def _create_parent_child_chunks(self, content: str, parent_index: int, file_name: str,
                                  file_id: str, source_data: list[dict], parent_chunk_id: str) -> tuple[Chunk, Chunk]:
        """创建父块和子块"""
        parent_chunk = self._create_chunk(
            content=content,
            chunk_index=parent_index,
            file_name=file_name,
            file_id=file_id,
            source_data=source_data,
            chunk_split_type="parent",
            parent_node=[parent_chunk_id],
            chunk_id=parent_chunk_id
        )

        child_chunk = self._create_chunk(
            content=content,
            chunk_index=1,
            file_name=file_name,
            file_id=file_id,
            source_data=source_data,
            chunk_split_type="child",
            parent_node=[parent_chunk_id],
            chunk_id=parent_chunk_id
        )

        return parent_chunk, child_chunk

    def _create_child_chunks(self, results: list, node_map: dict, file_name: str,
                            file_id: str, parent_chunk_id: str) -> tuple[list[Chunk], list[str]]:
        """创建子块并返回子块列表和父块引用列表"""
        parent_reference_chunk = []
        child_chunks = []

        for i, chunk_text in enumerate(results):
            child_chunk_id = self.generate_node_id()
            parent_reference_chunk.append(child_chunk_id)
            source_node = self._build_source_node_data(chunk_text, node_map)
            child_chunk = self._create_chunk(
                content=chunk_text["content"],
                chunk_index=i+1,
                file_name=file_name,
                file_id=file_id,
                source_data=source_node,
                chunk_split_type="child",
                parent_node=[parent_chunk_id],
                chunk_id=child_chunk_id
            )
            child_chunks.append(child_chunk)

        return child_chunks, parent_reference_chunk

    def _create_parent_chunks(self, parent_results: list, node_map: dict, file_name: str,
                            file_id: str, parent_chunk_id: str, parent_index: int,
                            parent_reference_chunk: list[str]) -> list[Chunk]:
        """创建父块"""
        parent_chunks = []

        for i, chunk_text in enumerate(parent_results):
            source_node = self._build_source_node_data(chunk_text, node_map)
            parent_chunk = self._create_chunk(
                content=chunk_text["content"],
                chunk_index=parent_index,
                file_name=file_name,
                file_id=file_id,
                source_data=source_node,
                chunk_split_type="parent",
                parent_node=parent_reference_chunk,
                chunk_id=parent_chunk_id
            )
            parent_chunks.append(parent_chunk)

        return parent_chunks

    def _get_node_range(self, parent_results: list, text: list) -> list:
        """获取节点范围"""
        try:
            pure_text = [item for item in text]
            if parent_results==[]:
                return []
            first_id = parent_results[0]["nodes"][0]
            last_id = parent_results[0]["nodes"][-1]
            idx_map = {n['id']: i for i, n in enumerate(pure_text)}
            start = idx_map.get(first_id)
            end = idx_map.get(last_id)

            if start is None or end is None:
                raise ValueError('result 首尾 id 在 pure_text 中不存在')

            return pure_text[start: end + 1]
        except Exception as e:
            raise

    def _process_text_node(self, sub_text: dict, text: list, node_map: dict, file_name: str,
                          file_id: str, child_splitter, parent_index: int) -> tuple[list[Chunk], int]:
        """处理文本节点"""
        sub_text_list = [sub_text]
        all_text, all_text2, spans_node = self.split_v1_v2(sub_text_list, self.separators)
        chunks = self._langchain_splitter.split_text(all_text)
        chunks = self._merge_small_chunks(chunks, self.chunk_size)
        # 保底逻辑：强制分割超过chunk_size的chunks
        # chunks = self._force_split_large_chunks(chunks, self.chunk_size)

        all_chunks = []
        current_parent_index = parent_index

        for chunk in chunks:
            parent_chunk = [chunk]
            parent_results = self.split_v2_v2(all_text2, spans_node, parent_chunk, text,
                                            self.chunk_overlap, False, self.separators)
            current_parent_index += 1

            ori_result = self._get_node_range(parent_results, text)
            sub_chunk = child_splitter.split_text(chunk)
            results = self.split_v2_v2(all_text2, spans_node, sub_chunk, ori_result,
                                     self.chunk_overlap, True, self.separators)

            # 创建父块和子块
            parent_chunk_id = self.generate_node_id()

            # 创建子块
            child_chunks, parent_reference_chunk = self._create_child_chunks(
                results, node_map, file_name, file_id, parent_chunk_id
            )
            all_chunks.extend(child_chunks)

            # 创建父块
            parent_chunks = self._create_parent_chunks(
                parent_results, node_map, file_name, file_id, parent_chunk_id,
                current_parent_index, parent_reference_chunk
            )
            all_chunks.extend(parent_chunks)

        return all_chunks, current_parent_index

    def _process_simple_node(self, sub_text: dict, node_map: dict, file_name: str,
                           file_id: str, parent_index: int) -> tuple[list[Chunk], int]:
        """处理简单节点（image/table）"""
        node_type = sub_text["type"]
        node_id = sub_text["id"]
        src_node = self._create_simple_node_source_data(node_id, node_map, node_type)

        parent_chunk_id = self.generate_node_id()
        parent_chunk, child_chunk = self._create_parent_child_chunks(
            sub_text.get("text",""), parent_index + 1, file_name, file_id, src_node, parent_chunk_id
        )

        return [parent_chunk, child_chunk], parent_index + 1

    def _is_node_referenced(self, node_id: str, node_type: str, text: list) -> bool:
        """检查节点是否被其他节点引用"""
        for item_node in text:
            if node_type == "table" and node_id in item_node.get("referenced_tables", []):
                return True
            elif node_type == "image" and node_id in item_node.get("referenced_images", []):
                return True
        return False

    def _process_node(self, sub_text: dict, text: list, node_map: dict, file_name: str,
                     file_id: str, child_splitter, parent_index: int) -> tuple[list[Chunk], int]:
        """统一的节点处理入口"""
        node_type = sub_text["type"]

        if node_type == "text":
            return self._process_text_node(sub_text, text, node_map, file_name, file_id, child_splitter, parent_index)
        elif node_type in ["image", "table"]:
            # 检查节点是否被引用，只有未被引用的节点才添加成块
            if not self._is_node_referenced(sub_text["id"], node_type, text):
                return self._process_simple_node(sub_text, node_map, file_name, file_id, parent_index)
            else:
                # 如果节点被引用，返回空列表
                return [], parent_index
        else:
            # 对于未知类型的节点，返回空列表
            logger.warning(f"未知节点类型: {node_type}")
            return [], parent_index

    def split(
            self, text: dict, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ):
        """使用递归字符分割器分割文本"""
        try:
            if not isinstance(text, list):
                return []
            if isinstance(self.sub_separator, list) and len(self.sub_separator) != 0:
                self.sub_separator = self.sub_separator + ["\n\n", "\n", "。", "！", "？", "；", "，", ",", " ", ""]
            else:
                self.sub_separator = ["\n\n", "\n", "。", "！", "？", "；", "，", ",", " ", ""]
            # 子块splitter分割器实例类
            child_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.sub_chunk_size,
                    chunk_overlap=0,
                    separators=self.sub_separator,
                    length_function=len
                )
            node_map = {item["id"]: item for item in text}
            all_chunks = []
            parent_index = 0

            # 使用第二种切分方案：基于去除换行符、空格符和分隔符的文本
            for sub_text in text:
                    chunks, parent_index = self._process_node(
                        sub_text, text, node_map, file_name, file_id, child_splitter, parent_index
                    )
                    all_chunks.extend(chunks)

            return all_chunks

        except Exception as e:
            logger.exception(f"递归字符分割失败: {str(traceback.format_exc())}")
            raise


class parent_by_title(BaseSplitter):
    """递归字符分割器"""

    def __init__(
            self, chunk_size: int = 500, chunk_overlap: int = 50, separators: Optional[list[str]] = None, **kwargs
    ):
        super().__init__(chunk_size, chunk_overlap, **kwargs)
        if len(separators) !=0 and isinstance(separators,list):
            self.separators=separators+["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        else:
            self.separators = separators or ["\n\n", "\n", "。", "！", "？", "；", "，",",", " ", ""]
        self.chunk_type = kwargs.get("chunk_type", None)
        self.sub_chunk_size = kwargs.get("sub_chunk_size", None)
        self.sub_separator = kwargs.get("sub_separator", None)
        self._langchain_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=self.separators, length_function=len
        )

    def _convert_to_source_node_format(self, ori_result: list[dict], node_map: dict) -> list[dict]:
        """将原始数据转换为_build_source_node_data的返回格式"""
        source_nodes = []
        for item in ori_result:
            node_id = item["id"]
            
            # 处理文本内容
            if node_map[node_id]["type"] == "table" or node_map[node_id]["type"] == "image":
                if type(node_map[node_id].get("caption", "")) != list and len(node_map[node_id].get("caption", [])) != 0:
                    text = node_map[node_id].get("caption", [""])[0] + node_map[node_id].get("text", "")
                else:
                    text = node_map[node_id].get("text", "")
            else:
                text = node_map[node_id].get("text", "")
            
            # 处理引用关系
            if item["type"] == "image":
                ref_image = True
                ref_table = False
            elif item["type"] == "table":
                ref_image = False
                ref_table = True
            else:
                ref_image = item.get("referenced_images", [])
                ref_table = item.get("referenced_tables", [])
            
            src_node = {
                "src_node_text": text,
                "src_node_bbox": node_map[node_id].get("bbox", []),
                "src_node_type": node_map[node_id]["type"],
                "src_node_id": node_map[node_id]["id"],
                "src_node_row": node_map[node_id].get("actual_row_idx", ""),
                "src_node_page": node_map[node_id]["page_idx"],
                "src_ref_image": ref_image,
                "src_ref_table": ref_table,
            }
            source_nodes.append(src_node)
        
        return source_nodes

    def add_text_level(self,text_dict):
        """
        给 text_list 中的每个字典添加 text_level 字段：
          - 以 1~6 个 # 开头并紧跟空格 -> text_level 为 # 的个数
          - # 超过 6 个也按 6 算
          - 不含 # 开头或格式不符 -> 0
        返回新的字典列表，原列表不被修改。
        """
        pattern = re.compile(r'^(#{1,6})\s+')  # 捕获 1~6 个 # 后跟空格
        out = []
        for item in text_dict:
            new_item = item.copy()
            if item.get("type","")=="text":
                match = pattern.match(item.get("text", ""))
                if match:
                    new_item["text_level"] = len(match.group(1))
                else:
                    new_item["text_level"] = 0
                out.append(new_item)
            else:
                out.append(new_item)
        return out

    from typing import List, Dict, Any

    Item = Dict[str, Any]

    def group_text_list(self,text_list):
        """
        对text_list进行分组处理

        分组逻辑：
        1. 第一轮：将连续相同状态的项分为一组
           - status=0: 不存在text_level字段或text_level为0
           - status=1: 存在text_level字段且text_level不为0

        2. 第二轮：按照特定规则重新组合
           - 如果第一项为0，则0为一块，后续10为一块，结尾的1为一块
           - 如果第一项为1，则10为一块，结尾的1为一块
        """

        # 第一轮分组：按状态分组
        temp_groups = []
        current_group = []
        current_status = None

        for item in text_list:
            # 判断当前项的状态
            if 'text_level' not in item or item.get('text_level', 0) == 0:
                item_status = 0
            else:
                item_status = 1

            # 如果状态改变，保存当前组并开始新组
            if current_status is not None and current_status != item_status:
                temp_groups.append((current_status, current_group))
                current_group = []

            current_status = item_status
            current_group.append(item)

        # 添加最后一组
        if current_group:
            temp_groups.append((current_status, current_group))


        # 第二轮分组：按照特定规则重新组合
        final_groups = []

        if not temp_groups:
            return final_groups

        # 获取状态序列
        status_sequence = [status for status, _ in temp_groups]

        i = 0
        while i < len(temp_groups):
            current_status, current_group = temp_groups[i]

            if current_status == 0:
                # 如果当前是0，则0为一块
                final_groups.append(current_group)
                i += 1
            else:
                # 如果当前是1，需要判断后续情况
                if i + 1 < len(temp_groups):
                    next_status, next_group = temp_groups[i + 1]
                    if next_status == 0:
                        # 1后面是0，则10为一块
                        combined_group = current_group + next_group
                        final_groups.append(combined_group)
                        i += 2
                    else:
                        # 1后面还是1，则1为一块
                        final_groups.append(current_group)
                        i += 1
                else:
                    # 最后一项是1，则1为一块
                    final_groups.append(current_group)
                    i += 1

        return final_groups

    def split(
            self, text: dict, file_name: str = "", file_id: str = "", source_data: Optional[list[dict[str, Any]]] = None
    ):
        """使用递归字符分割器分割文本"""
        try:
            # 子块splitter分割器实例类
            # if self.sub_separator==[] or self.sub_separator==None:
            #     self.sub_separator=['\n']

            # if len(self.sub_separator) != 0 and isinstance(self.sub_separator, list):
            if isinstance(self.sub_separator, list) and len(self.sub_separator) != 0:
                self.sub_separator = self.sub_separator + ["\n\n", "\n", "。", "！", "？", "；", "，", ",", " ", ""]
            else:
                self.sub_separator =  ["\n\n", "\n", "。", "！", "？", "；", "，", ",", " ", ""]
            child_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.sub_chunk_size,
                    chunk_overlap=0,
                    separators=self.sub_separator,
                    length_function=len
                )
            node_map = {item["id"]: item for item in text}
            all_chunks=[]
            all_texts=self.group_by_page_idx(text)
            parent_index=0

            level_text=self.add_text_level(text)
            group_texts=self.group_text_list(level_text)
            last_parent_chunk_obj=None
            last_parent_last_node_id=None

            for group_text in group_texts:
                child_index = 0
                group_title = ''.join(item['text'] for item in group_text if item.get('text_level',"") != 0 and item.get('type',"")=="text")
                filtered_group_text = [item for item in group_text if item.get('text_level', 0) == 0]

                # 按标题分组
                if isinstance(filtered_group_text, list):
                    # 使用第二种切分方案：基于去除换行符、空格符和分隔符的文本
                    all_text, all_text2, spans_node = self.split_v1_v2(filtered_group_text, self.separators)
                    #先对父块进行切分
                    chunks = self._langchain_splitter.split_text(all_text)
                    # 合并小于chunk_size的chunks
                    # chunks = self._merge_small_chunks(chunks, self.chunk_size)
                    # 保底逻辑：强制分割超过chunk_size的chunks
                    # chunks = self._force_split_large_chunks(chunks, self.chunk_size)
                    # 一个chunks是一个父块
                    if chunks==[] and all_text=="":
                        # 如果一页是标题后只有图片/表格等非文本节点的情况下的特殊处理

                        parent_chunk_id = self.generate_node_id()
                        parent_reference_chunk = []
                        
                        # 为非文本节点创建父子块
                        for item in filtered_group_text:
                            if item["type"] in ["image", "table"]:
                                # 检查节点是否被引用
                                is_referenced = False
                                for other_item in group_text:
                                    if (item["id"] in other_item.get("referenced_images", []) or 
                                        item["id"] in other_item.get("referenced_tables", [])):
                                        is_referenced = True
                                        break
                                
                                # 只有未被引用的节点才创建块
                                if not is_referenced and item.get("text", "") != "":
                                    child_chunk_id = self.generate_node_id()
                                    parent_reference_chunk.append(child_chunk_id)
                                    
                                    # 创建子块
                                    source_node = self._build_source_node_data(
                                        {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]}, 
                                        node_map
                                    )
                                    child_index+=1
                                    # 子块的content拼接title，但ori_content保留原始内容
                                    child_content = item["text"]
                                    child_content_with_title = (group_title + "\n" if group_title else "") + child_content
                                    child_chunk = self._create_chunk(
                                        content=child_content_with_title,
                                        chunk_index=child_index,
                                        file_name=file_name,
                                        file_id=file_id,
                                        source_data=source_node,
                                        chunk_split_type="child",
                                        parent_node=[parent_chunk_id],
                                        chunk_id=child_chunk_id,
                                        ori_content=child_content
                                    )
                                    all_chunks.append(child_chunk)
                        
                        # 如果有子块，创建父块
                        if parent_reference_chunk:
                            # 创建父块内容（标题 + 所有非文本节点的文本）
                            parent_content = group_title + "\n" if group_title else ""
                            for item in filtered_group_text:
                                if item["type"] in ["image", "table"] and item.get("text", "") != "":
                                    parent_content += item["text"] + "\n"
                            
                            # 创建父块的源数据
                            parent_source_nodes = []
                            # 添加 title 节点的源数据
                            for item in group_text:
                                if item.get('text_level', 0) != 0 and item.get('type', "") == "text":
                                    parent_source_nodes.extend(self._build_source_node_data(
                                        {"type": "chunk_text", "content": item["text"], "nodes": [item["id"]]}, 
                                        node_map
                                    ))
                            # 添加非文本节点的源数据
                            for item in filtered_group_text:
                                if item["type"] in ["image", "table"] and item.get("text", "") != "":
                                    parent_source_nodes.extend(self._build_source_node_data(
                                        {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]}, 
                                        node_map
                                    ))
                            parent_index += 1
                            parent_chunk = self._create_chunk(
                                content=parent_content.strip(),
                                chunk_index=parent_index,
                                file_name=file_name,
                                file_id=file_id,
                                source_data=parent_source_nodes,
                                chunk_split_type="parent",
                                parent_node=parent_reference_chunk,
                                chunk_id=parent_chunk_id
                            )
                            all_chunks.append(parent_chunk)
                    else:
                        # 正常的父子块处理逻辑
                        temp=-1
                        for chunk in chunks:
                            child_index = 0
                            # 每一个chunk是一个父块
                            # 找到当前chunk对应的节点列表
                            parent_reference_chunk = []
                            parent_chunk_id = self.generate_node_id()
                            parent_chunk=[chunk]
                            parent_results= self.split_v2_v2(all_text2, spans_node, parent_chunk, filtered_group_text, self.chunk_overlap, False, self.separators)
                            pure_text = [item for item in filtered_group_text]
                            if parent_results != []:
                                first_id = parent_results[0]["nodes"][0]
                                last_id = parent_results[0]["nodes"][-1]
                                idx_map = {n['id']: i for i, n in enumerate(pure_text)}
                                start = idx_map.get(first_id)
                                if temp+2<=start:
                                    # 这种特殊情况下，temp+1到start之间的所有元素都单独成为一块
                                    for idx in range(temp+1, start):
                                        if pure_text[idx]["type"] in ["image", "table"]:
                                            # 检查节点是否被引用
                                            is_referenced = False
                                            for other_item in filtered_group_text:
                                                if (pure_text[idx]["id"] in other_item.get("referenced_images", []) or
                                                        pure_text[idx]["id"] in other_item.get("referenced_tables", [])):
                                                    is_referenced = True
                                                    break

                                            # 只有未被引用的节点才创建块
                                            if not is_referenced:
                                                limp_child_chunk_id = self.generate_node_id()
                                                limp_parent_chunk_id = self.generate_node_id()
                                                limp_parent_reference_chunk=[limp_child_chunk_id]

                                                # 创建子块
                                                source_node = self._build_source_node_data(
                                                    {"type": f"chunk_{pure_text[idx]['type']}", "content": pure_text[idx]["text"],
                                                     "nodes": [pure_text[idx]["id"]]},
                                                    node_map
                                                )
                                                child_index+=1
                                                # 子块的content拼接title，但ori_content保留原始内容
                                                limp_content = pure_text[idx]["text"]
                                                limp_content_with_title = (group_title + "\n" if group_title else "") + limp_content
                                                limp_pic = self._create_chunk(
                                                    content=limp_content_with_title,
                                                    chunk_index=child_index,
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=source_node,
                                                    chunk_split_type="child",
                                                    parent_node=[limp_parent_chunk_id],
                                                    chunk_id=limp_child_chunk_id,
                                                    ori_content=limp_content
                                                )
                                                all_chunks.append(limp_pic)
                                                parent_index += 1
                                                # 创建父块的源数据，包含 title 节点和非文本节点
                                                limp_parent_source_nodes = []
                                                # 添加 title 节点的源数据
                                                for item in group_text:
                                                    if item.get('text_level', 0) != 0 and item.get('type', "") == "text":
                                                        limp_parent_source_nodes.extend(self._build_source_node_data(
                                                            {"type": "chunk_text", "content": item["text"], "nodes": [item["id"]]}, 
                                                            node_map
                                                        ))
                                                # 添加非文本节点的源数据
                                                limp_parent_source_nodes.extend(source_node)
                                                limp_pic2 = self._create_chunk(
                                                    content=group_title + "\n" + pure_text[idx]["text"],
                                                    chunk_index=parent_index,
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=limp_parent_source_nodes,
                                                    chunk_split_type="parent",
                                                    parent_node=limp_parent_reference_chunk,
                                                    chunk_id=limp_parent_chunk_id
                                                )
                                                all_chunks.append(limp_pic2)
                                                parent_index +=1
                                    # 中间的单独成一个子块
                                    # print("11")
                                end = idx_map.get(last_id)
                                if start is None or end is None:
                                    raise ValueError('result 首尾 id 在 pure_text 中不存在')
                                temp=end

                                # 3. 取出闭区间 [start, end] 所有元素，并添加后续连续的图片
                                ori_result = pure_text[start: end + 1]
                            else:
                                ori_result=[]
                            # 检查 end + 1 后面是否有连续的图片/表格节点

                            # current_idx = end + 1
                            # while current_idx < len(pure_text):
                            #     if pure_text[current_idx]["type"] in ["image", "table"]:
                            #         # 检查节点是否被引用
                            #         is_referenced = False
                            #         for other_item in filtered_group_text:
                            #             if (pure_text[current_idx]["id"] in other_item.get("referenced_images", []) or
                            #                 pure_text[current_idx]["id"] in other_item.get("referenced_tables", [])):
                            #                 is_referenced = True
                            #                 break
                            #
                            #         # 只有未被引用的图片/表格节点才添加到ori_result中
                            #         if not is_referenced:
                            #             ori_result.append(pure_text[current_idx])
                            #             current_idx += 1
                            #         else:
                            #             break
                            #     else:
                            #         break
                            # start_idx = next(i for i, item in enumerate(pure_text) if item['id'] == first_id)
                            # ori_result = pure_text[start_idx: start_idx + len(parent_results[0]["nodes"])]

                            sub_chunk = child_splitter.split_text(chunk)
                            results = self.split_v2_v2(all_text2, spans_node, sub_chunk, ori_result, self.chunk_overlap, True,
                                                       self.separators)
                            # 添加子块
                            if last_parent_chunk_obj and last_parent_last_node_id:
                                curr_first_id = ori_result[0]["id"] if ori_result else None

                                ordered_nodes = list(node_map.values())
                                id_to_index = {n.get("id"): i for i, n in enumerate(ordered_nodes)}
                                prev_idx = id_to_index.get(last_parent_last_node_id)
                                curr_idx = id_to_index.get(curr_first_id)
                                if prev_idx is not None and curr_idx is not None and prev_idx + 1 < curr_idx:
                                    gap_items = ordered_nodes[prev_idx + 1: curr_idx]
                                    additional_content_parts = []
                                    for gap_item in gap_items:
                                        if gap_item.get("type") in ["image", "table"] and gap_item.get("text", ""):
                                            # 检查是否被引用
                                            is_ref = False
                                            for other_item in node_map.values():
                                                if (gap_item["id"] in other_item.get("referenced_images", []) or
                                                    gap_item["id"] in other_item.get("referenced_tables", [])):
                                                    is_ref = True
                                                    break
                                            if not is_ref:
                                                # 创建子块并挂到上一父块
                                                gap_child_id = self.generate_node_id()
                                                gap_source = self._build_source_node_data(
                                                    {"type": f"chunk_{gap_item['type']}", "content": gap_item["text"], "nodes": [gap_item["id"]]},
                                                    node_map
                                                )
                                                # 子块的content拼接title，但ori_content保留原始内容
                                                gap_content = gap_item["text"]
                                                gap_content_with_title = (group_title + "\n" if group_title else "") + gap_content
                                                gap_child = self._create_chunk(
                                                    content=gap_content_with_title,
                                                    chunk_index=len(last_parent_chunk_obj.metadata.parent_node) + 1,
                                                    file_name=file_name,
                                                    file_id=file_id,
                                                    source_data=gap_source,
                                                    chunk_split_type="child",
                                                    parent_node=[last_parent_chunk_obj.metadata.chunk_id],
                                                    chunk_id=gap_child_id,
                                                    ori_content=gap_content
                                                )
                                                all_chunks.append(gap_child)
                                                last_parent_chunk_obj.metadata.parent_node.append(gap_child_id)
                                                additional_content_parts.append(gap_item["text"])
                                                # 同步源数据到父块
                                                last_parent_chunk_obj.metadata.source_data.extend(gap_source)
                                    if additional_content_parts:
                                        # 将缺失图片描述追加到上一个父块内容末尾
                                        last_parent_chunk_obj.content += "\n" + "\n".join(additional_content_parts)
                            for i, chunk_text in enumerate(results):
                                child_chunk_id=self.generate_node_id()
                                parent_reference_chunk.append(child_chunk_id)
                                source_node = self._build_source_node_data(chunk_text, node_map)
                                child_index += 1
                                # 子块的content拼接title，但ori_content保留原始内容
                                child_content = chunk_text["content"]
                                child_content_with_title = (group_title + "\n" if group_title else "") + child_content
                                child_chunk = self._create_chunk(
                                    content=child_content_with_title,
                                    chunk_index=child_index,
                                    file_name=file_name,
                                    file_id=file_id,
                                    source_data=source_node,
                                    chunk_split_type="child",
                                    parent_node=[parent_chunk_id],
                                    chunk_id=child_chunk_id,
                                    ori_content=child_content
                                )
                                all_chunks.append(child_chunk)
                            
                            # 检查是否存在未处理的图片/表格节点，让它们单独成为子块
                            processed_node_ids = set()
                            for chunk_text in results:
                                processed_node_ids.update(chunk_text["nodes"])
                            
                            # 使用原始的filtered_group_text参数来检查未处理的图片/表格节点
                            for item in ori_result:
                                if (item["type"] in ["image", "table"] and
                                    item["id"] not in processed_node_ids and
                                    item.get("text", "") != ""):
                                    # 检查节点是否被引用
                                    is_referenced = False
                                    for other_item in group_text:
                                        if (item["id"] in other_item.get("referenced_images", []) or
                                            item["id"] in other_item.get("referenced_tables", [])):
                                            is_referenced = True
                                            break
                                    
                                    # 只有未被引用的节点才创建块
                                    if not is_referenced:
                                        child_chunk_id = self.generate_node_id()
                                        parent_reference_chunk.append(child_chunk_id)
                                        
                                        # 创建子块
                                        source_node = self._build_source_node_data(
                                            {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]}, 
                                            node_map
                                        )
                                        child_index+=1
                                        # 子块的content拼接title，但ori_content保留原始内容
                                        unprocessed_content = item["text"]
                                        unprocessed_content_with_title = (group_title + "\n" if group_title else "") + unprocessed_content
                                        parent_chunk = self._create_chunk(
                                            content=unprocessed_content_with_title,
                                            chunk_index=child_index,
                                            file_name=file_name,
                                            file_id=file_id,
                                            source_data=source_node,
                                            chunk_split_type="child",
                                            parent_node=[parent_chunk_id],
                                            chunk_id=child_chunk_id,
                                            ori_content=unprocessed_content
                                        )
                                        all_chunks.append(parent_chunk)
                            
                            # 添加父块
                            for i, chunk_text in enumerate(parent_results):
                                # 获取原始父块的源数据
                                source_node = self._build_source_node_data(chunk_text, node_map)
                                
                                # 获取已处理的节点ID集合
                                processed_node_ids = set()
                                for chunk_text_temp in results:
                                    processed_node_ids.update(chunk_text_temp["nodes"])
                                
                                # 在转换为 source_node 之前，补充 ori_result 中被文本引用的图片/表格节点，避免重复

                                # 添加 title 节点的源数据
                                for item in group_text:
                                    if item.get('text_level', 0) != 0 and item.get('type', "") == "text":
                                        title_source_node = self._build_source_node_data(
                                            {"type": "chunk_text", "content": item["text"], "nodes": [item["id"]]}, 
                                            node_map
                                        )
                                        source_node.extend(title_source_node)
                                
                                # 添加未处理图片/表格节点的源数据
                                for item in filtered_group_text:
                                    if (item["type"] in ["image", "table"] and 
                                        item["id"] not in processed_node_ids and
                                        item.get("text", "") != ""):
                                        # 检查节点是否被引用
                                        is_referenced = False
                                        for other_item in group_text:
                                            if (item["id"] in other_item.get("referenced_images", []) or 
                                                item["id"] in other_item.get("referenced_tables", [])):
                                                is_referenced = True
                                                break
                                        
                                        # 只有未被引用的节点才添加到父块的源数据中
                                        if not is_referenced:
                                            additional_source_node = self._build_source_node_data(
                                                {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]}, 
                                                node_map
                                            )
                                            source_node.extend(additional_source_node)
                                
                                # 构建完整的父块内容，以chunk为基础，按ori_result顺序插入未挂载图片
                                parent_content = (group_title + "\n" if group_title else "") + chunk_text["content"]
                                processed_node_ids = set()
                                for chunk_text_item in results:
                                    if chunk_text_item["type"] == "chunk_text":
                                        processed_node_ids.update(chunk_text_item["nodes"])
                                # 找到未挂载的图片/表格节点，按ori_result顺序插入到正确位置
                                unmounted_items = []
                                is_referenced = False
                                for item in ori_result:
                                    if (item["type"] in ["image", "table"] and 
                                        item["id"] not in processed_node_ids and
                                        item.get("text", "") != ""):
                                        # 检查节点是否被引用
                                        is_referenced = False
                                        for other_item in group_text:
                                            if (item["id"] in other_item.get("referenced_images", []) or 
                                                item["id"] in other_item.get("referenced_tables", [])):
                                                is_referenced = True
                                                break
                                        
                                        # 只有未被引用的节点才需要插入
                                        if not is_referenced:
                                            unmounted_items.append(item)
                                
                                # 如果有未挂载的图片，需要重新构建内容以保持正确顺序
                                if unmounted_items:
                                    # 按ori_result顺序重新构建内容
                                    content_parts = []
                                    
                                    # 添加标题（如果有）
                                    if group_title:
                                        content_parts.append(group_title)
                                    
                                    # 将chunk按行分割
                                    chunk_lines = chunk.split('\n')
                                    
                                    # 按ori_result顺序构建内容
                                    chunk_line_idx = 0
                                    for item in ori_result:
                                        if item["id"] in processed_node_ids and item["type"] == "text":
                                            # 对于已处理的文本节点，使用chunk_lines中的内容
                                            if chunk_line_idx < len(chunk_lines):
                                                content_parts.append(chunk_lines[chunk_line_idx])
                                                chunk_line_idx += 1
                                        elif item in unmounted_items:
                                            # 对于未挂载的图片/表格节点
                                            content_parts.append(item["text"])
                                    
                                    # 如果还有剩余的chunk_lines，添加到末尾
                                    while chunk_line_idx < len(chunk_lines):
                                        content_parts.append(chunk_lines[chunk_line_idx])
                                        chunk_line_idx += 1
                                    
                                    # 合并所有内容部分
                                    parent_content = '\n'.join(content_parts)

                                expanded_result = []
                                try:
                                    existing_ids = set([n.get("id") for n in ori_result])
                                    for base_item in ori_result:
                                        expanded_result.append(base_item)
                                        if base_item.get("type") == "text":
                                            for ref_img_id in base_item.get("referenced_images", []) or []:
                                                ref_node = node_map.get(ref_img_id)
                                                if ref_node and ref_node.get("id") not in existing_ids:
                                                    expanded_result.append(ref_node)
                                                    existing_ids.add(ref_node.get("id"))
                                            for ref_tbl_id in base_item.get("referenced_tables", []) or []:
                                                ref_node = node_map.get(ref_tbl_id)
                                                if ref_node and ref_node.get("id") not in existing_ids:
                                                    expanded_result.append(ref_node)
                                                    existing_ids.add(ref_node.get("id"))
                                    # ori_result = expanded_result
                                except Exception:
                                    pass
                                # 将ori_result转换为source_node格式
                                source_node_data = self._convert_to_source_node_format(expanded_result, node_map)
                                
                                # 添加 title 节点的源数据
                                for item in group_text:
                                    if item.get('text_level', 0) != 0 and item.get('type', "") == "text":
                                        title_source_node = self._build_source_node_data(
                                            {"type": "chunk_text", "content": item["text"], "nodes": [item["id"]]}, 
                                            node_map
                                        )
                                        source_node_data.extend(title_source_node)
                                
                                if is_referenced:
                                    parent_content= (group_title + "\n" if group_title else "") + child_content
                                parent_index += 1
                                parent_chunk = self._create_chunk(
                                    content=parent_content,
                                    chunk_index=parent_index,
                                    file_name=file_name,
                                    file_id=file_id,
                                    source_data=source_node_data,
                                    chunk_split_type="parent",
                                    parent_node=parent_reference_chunk,
                                    chunk_id=parent_chunk_id
                                )
                                all_chunks.append(parent_chunk)
                                # 记录当前父块，用于下一父块进行跨父块缺失节点补齐判断
                                try:
                                    if ori_result:
                                        last_parent_last_node_id = ori_result[-1]["id"]
                                    last_parent_chunk_obj = parent_chunk
                                except Exception:
                                    pass


            # 处理最后的未挂载图片/表格节点
            # if all_chunks:
            #     # 找到最后一个父块
            #     last_parent_chunk = None
            #     for chunk in reversed(all_chunks):
            #         if chunk.metadata.chunk_split_type == "parent":
            #             last_parent_chunk = chunk
            #             break
            #
            #     if last_parent_chunk:
            #         # 检查输入text的最后若干项是否为未挂载的图片/表格节点
            #         trailing_unmounted_items = []
            #         for i in range(len(text) - 1, -1, -1):
            #             item = text[i]
            #             if item["type"] in ["image", "table"] and item.get("text", "") != "":
            #                 # 检查节点是否被引用
            #                 is_referenced = False
            #                 for other_item in text:
            #                     if (item["id"] in other_item.get("referenced_images", []) or
            #                         item["id"] in other_item.get("referenced_tables", [])):
            #                         is_referenced = True
            #                         break
            #
            #                 # 只有未被引用的节点才需要处理
            #                 if not is_referenced:
            #                     trailing_unmounted_items.insert(0, item)  # 保持原始顺序
            #                 else:
            #                     break
            #             else:
            #                 break
            #
            #         # 如果有未挂载的图片/表格节点，将它们作为最后一个父块的子块
            #         if trailing_unmounted_items:
            #             # 为每个未挂载的图片/表格节点创建子块
            #             for item in trailing_unmounted_items:
            #                 child_chunk_id = self.generate_node_id()
            #
            #                 # 创建子块
            #                 source_node = self._build_source_node_data(
            #                     {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]},
            #                     node_map
            #                 )
            #
            #                 child_chunk = self._create_chunk(
            #                     content=item["text"],
            #                     chunk_index=len(last_parent_chunk.metadata.parent_node) + 1,
            #                     file_name=file_name,
            #                     file_id=file_id,
            #                     source_data=source_node,
            #                     chunk_split_type="child",
            #                     parent_node=[last_parent_chunk.metadata.chunk_id],
            #                     chunk_id=child_chunk_id
            #                 )
            #                 all_chunks.append(child_chunk)
            #
            #                 # 更新父块的parent_node列表
            #                 last_parent_chunk.metadata.parent_node.append(child_chunk_id)
            #
            #             # 更新最后一个父块的内容，添加未挂载图片的描述
            #             additional_content = []
            #             for item in trailing_unmounted_items:
            #                 additional_content.append(item["text"])
            #
            #             if additional_content:
            #                 # 将未挂载图片的描述添加到父块内容的末尾
            #                 last_parent_chunk.content += "\n" + "\n".join(additional_content)
            #
            #                 # 更新父块的源数据
            #                 for item in trailing_unmounted_items:
            #                     additional_source_node = self._build_source_node_data(
            #                         {"type": f"chunk_{item['type']}", "content": item["text"], "nodes": [item["id"]]},
            #                         node_map
            #                     )
            #                     last_parent_chunk.metadata.source_data.extend(additional_source_node)

            return all_chunks

        except Exception as e:
            logger.exception(f"递归字符分割失败: {str(traceback.format_exc())}")
            raise



class SplitterFactory:
    """分割器工厂类"""

    _splitters = {
        "CharacterTextSplitter": CharacterSplitter,
        "RecursiveCharacterTextSplitter": RecursiveCharacterSplitter,
        "SpacyTextSplitter": SpacySplitter,
        "parent_by_page":parent_by_page,
        "parent_by_paragraph":parent_by_paragraph,
        "parent_by_title":parent_by_title
        # "ChineseRecursiveTextSplitter": ChineseRecursiveSplitter,
        # "SentenceSplitter": SentenceSplitter,
        # "ParagraphSplitter": ParagraphSplitter,
    }

    @classmethod
    def get_splitter(cls, method: str, **kwargs) -> BaseSplitter:
        """根据方法名获取分割器实例"""
        if method not in cls._splitters:
            raise ValueError(f"不支持的分割方法: {method}")

        splitter_class = cls._splitters[method]
        return splitter_class(**kwargs)

    @classmethod
    def register_splitter(cls, name: str, splitter_class: type):
        """注册新的分割器"""
        if not issubclass(splitter_class, BaseSplitter):
            raise ValueError("分割器类必须继承自BaseSplitter")
        cls._splitters[name] = splitter_class

    @classmethod
    def get_available_splitters(cls) -> list[str]:
        """获取所有可用的分割器名称"""
        return list(cls._splitters.keys())


class SplitterService:
    """分割服务主类，与现有项目集成"""

    def __init__(self):
        self.factory = SplitterFactory()

    async def split_text(
        self,
        text: list,
        method: str = "RecursiveCharacterTextSplitter",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separator: Union[str, list[str]] = "\n",
        file_name: str = "",
        file_id: str = "",
        source_data: Optional[list[dict[str, Any]]] = None,
        chunk_type: Optional[str] = None,
        sub_chunk_size: Optional[int] = None,
        sub_separator: Optional[list] = None,
        **kwargs,
    ) -> list[Chunk]:
        """
        分割文本的主方法，与现有项目的embedding_document方法兼容

        Args:
            text: 要分割的文本
            method: 分割方法
            chunk_size: 块大小
            chunk_overlap: 重叠大小
            separator: 分隔符
            file_name: 文件名
            file_id: 文件ID
            source_data: 源数据
            **kwargs: 其他参数

        Returns:
            Chunk列表
        """
        try:
            # 处理分隔符参数
            if isinstance(separator, list):
                separators = separator
                separator_str = separator[0] if separator else "\n"
            else:
                separators = [separator]
                separator_str = separator

            # 根据方法名构建参数
            splitter_kwargs = {
                "chunk_size": chunk_size,
                "chunk_overlap": chunk_overlap,
                "chunk_type": chunk_type,
                "sub_chunk_size": sub_chunk_size,
                "sub_separator": sub_separator,
                **kwargs
            }

            # 为不同的分割器添加特定参数
            if method == "CharacterTextSplitter":
                splitter_kwargs["separator"] = separator_str
            elif method == "RecursiveCharacterTextSplitter":
                splitter_kwargs["separators"] = separators
            elif method == "SpacyTextSplitter":
                splitter_kwargs["separator"] = separator_str

            elif method == "parent_by_page":
                splitter_kwargs["separators"] = separators
            elif method == "parent_by_paragraph":
                splitter_kwargs["separators"] = separators
            elif method == "parent_by_title":
                splitter_kwargs["separators"] = separators




            # 获取分割器实例
            splitter = self.factory.get_splitter(method, **splitter_kwargs)

            # 执行分割
            chunks = splitter.split(text=text, file_name=file_name, file_id=file_id, source_data=source_data)

            logger.info(f"文本分割完成，方法: {method}, 块数量: {len(chunks)}")
            return chunks

        except Exception as e:
            logger.exception(f"文本分割失败: {str(traceback.format_exc())}")
            raise

    async def split_text_simple(
        self,
        text: list,
        method: str = "RecursiveCharacterTextSplitter",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separator: Union[str, list[str]] = "\n",
        chunk_type: Optional[str] = None,
        sub_chunk_size: Optional[int] = None,
        sub_separator: Optional[list] = None,
        **kwargs,
    ) -> list[str]:
        try:

            chunks = await self.split_text(
                text=text,
                method=method,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=separator,
                chunk_type=chunk_type,
                sub_chunk_size=sub_chunk_size,
                sub_separator=sub_separator,
                **kwargs,
            )
            print("1111111111111111")
            if kwargs.get("is_embedding", False) == True:
                return chunks
            else:
                # 判断是否为父子分块

                if chunk_type=="parent":
                    # 父子分块：按照 chunk_result_query_v2 的逻辑处理返回值
                    result = []
                    for chunk in chunks:
                        if hasattr(chunk, 'metadata') and chunk.metadata.chunk_split_type == 'parent':
                            # 处理父级切片
                            parent_result = {
                                "content": chunk.content,
                                "metadata": {
                                    "chunk_split_type": "parent",
                                    "chunk_index": chunk.metadata.chunk_index,
                                    "parent_node": chunk.metadata.parent_node,
                                    "chunk_id": chunk.metadata.chunk_id,
                                    "child_chunks": []
                                }
                            }

                            # 查找并添加子切片
                            for child_chunk in chunks:
                                if (hasattr(child_chunk, 'metadata') and
                                    child_chunk.metadata.chunk_split_type == 'child' and
                                    chunk.metadata.chunk_id in child_chunk.metadata.parent_node):

                                    child_result = {
                                        "content": child_chunk.content,
                                        "metadata": {
                                            "chunk_split_type": "child",
                                            "chunk_index": child_chunk.metadata.chunk_index,
                                            "parent_node": child_chunk.metadata.parent_node,
                                            "chunk_id": child_chunk.metadata.chunk_id
                                        }
                                    }
                                    parent_result["metadata"]["child_chunks"].append(child_result)

                            result.append(parent_result)

                    return result
                else:
                    # 传统分块：只返回文本内容
                    return [chunk.content for chunk in chunks]

        except Exception as e:
            logger.exception(f"简化文本分割失败: {str(traceback.format_exc())}")
            raise

    def get_available_methods(self) -> dict[str, list[int]]:
        """获取可用的分割方法及其默认参数，与现有API兼容"""
        return {
            "RecursiveCharacterTextSplitter": [500, 50],
            "SpacyTextSplitter": [500, 50],
            "CharacterTextSplitter": [500, 50],
            "ChineseRecursiveTextSplitter": [500, 50],
            "SentenceSplitter": [500, 50],
            "ParagraphSplitter": [500, 50],
        }
    
    async def split_text_v2(
        self,
        text: list,
        method: str = "RecursiveCharacterTextSplitter",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separator: Union[str, list[str]] = "\n",
        file_name: str = "",
        file_id: str = "",
        source_data: Optional[list[dict[str, Any]]] = None,
        **kwargs,
    ) -> list[Chunk]:
        """
        使用第二种切分方案分割文本的便捷方法（基于去除换行符、空格符和分隔符的文本）
        
        Args:
            text: 要分割的文本
            method: 分割方法
            chunk_size: 块大小
            chunk_overlap: 重叠大小
            separator: 分隔符
            file_name: 文件名
            file_id: 文件ID
            source_data: 源数据
            **kwargs: 其他参数

        Returns:
            Chunk列表
        """
        return await self.split_text(
            text=text,
            method=method,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separator=separator,
            file_name=file_name,
            file_id=file_id,
            source_data=source_data,
            **kwargs,
        )

# 全局分割服务实例
splitter_service = SplitterService()


# 导出主要类和函数
__all__ = [
    "BaseSplitter",
    "CharacterSplitter",
    "parent_by_page",
    "parent_by_paragraph",
    "parent_by_title",
    "Chunk",
    "ChunkMetadata",
    "RecursiveCharacterSplitter",
    "SpacySplitter",
    "SplitterFactory",
    "SplitterService",
    # "embedding_document",
    "splitter_service",
]
