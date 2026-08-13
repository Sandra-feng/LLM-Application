#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@File       ：QAKnowledgeRetrieval.py
@Description:
@Author     ：fengzongling
@Date       ：2025/10/9 10:10
"""

import copy
import json

from bson import ObjectId
from loguru import logger

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from service_model_manage.service.model_family_service import ModelFamilyService
from service_synonym_manage.entity.synonym_entity import SynonymGroupModel
from service_synonym_manage.service.synonym_group_service import SynonymGroupService
from service_toolset_manage.service.toolset_service import BochaService
from base_configs.model_config import ModelConfig
from langchain_openai import ChatOpenAI
from langchain_core.tools import tool
from langchain.agents import create_agent


class KnowledgeRetrievalLLMQA:
    def __init__(self, request, knwolege_retrieval):
        self.request = request
        self.knwolege_retrieval = knwolege_retrieval

    @staticmethod
    def _build_chunk_content_with_images(chunk_results: list) -> list:
        """在chunk_results中添加图片描述，返回修改后的chunk_results列表"""
        if not chunk_results:
            return []

        # 直接修改原始的chunk_results列表
        for chunk in chunk_results:
            chunk_content = chunk.get("chunk_content", "")
            reference_nodes = chunk.get("reference_node", [])

            # 提取图片节点的描述
            image_descriptions = []
            for node in reference_nodes:
                if node.get("src_node_type") == "image" or node.get("src_node_type") == "table":
                    image_text = node.get("src_node_text", "")
                    if image_text.strip():
                        if node.get("src_node_type") == "image":
                            image_descriptions.append(f"<image>{image_text}</image>")
                        elif node.get("src_node_type") == "table":
                            image_descriptions.append(f"<table>{image_text}</table>")

            # 如果有图片描述，添加到chunk内容中
            if image_descriptions:
                import re

                pattern = r"(图\d+|图[一二三四五六七八九十百千万]+)"

                def replace_image_match(match):
                    figure_ref = match.group(1)
                    # 找到对应的图片描述（如果有多个图片，按顺序添加）
                    description = ""
                    if image_descriptions:
                        description = image_descriptions.pop(0)
                    return f"{figure_ref}{description}"

                # 替换第一个匹配的图引用
                modified_content = re.sub(pattern, replace_image_match, chunk_content, count=1)

                # 如果还有剩余的图片描述，添加到末尾
                if image_descriptions:
                    modified_content += "\n" + "\n".join(image_descriptions)

                # 更新chunk中的内容
                chunk["chunk_content"] = modified_content

        # 返回修改后的chunk_results列表
        return chunk_results

    @staticmethod
    def _get_file_urls_from_child(child: dict) -> str:
        """
        从child节点获取文件URL，处理MongoDB查询可能返回None的情况
        :param child: 子节点数据
        :return: 文件URL字符串
        """
        # 如果已有PDF格式的file_urls，直接返回
        file_urls = child.get("file_urls", "")
        if file_urls.endswith(".pdf"):
            return file_urls

        # 获取file_id，先从child中获取，如果获取不到，再从entity中获取
        file_id = child.get("file_id") if "file_id" in child else child.get("entity", {}).get("file_id", "")

        # 查询文件信息文档
        file_doc = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, doc_id=file_id
        )

        # 处理查询结果为None的情况
        if file_doc is None:
            logger.warning(f"文件信息未找到 | file_id={file_id}")
            return child.get("file_urls", child.get("entity", {}).get("file_urls", ""))

        # 返回pdf_path，如果不存在则使用默认值
        return file_doc.get("pdf_path", child.get("file_urls", child.get("entity", {}).get("file_urls", "")))

    async def process_v1_file(self, model_list, citation_open):
        """执行检索并返回 retrival_info 和 chunk_content"""
        if not self.request.retrival_params.id:
            logger.info("未挂载知识库检索")
            return [], ""

        # 获取知识库名称
        kb_doc = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(self.request.retrival_params.id)
        )
        kb_name = kb_doc.get("kb_name", "")

        # 调用检索
        retrival_result = await self.knwolege_retrieval(self.request.retrival_params)
        retrival_result = json.loads(retrival_result.body)

        # 解析结果
        chunk_results = retrival_result.get("data", {}).get("results", [])
        logger.info("知识库检索完成 | 结果数量={} | ", len(chunk_results))

        retrival_info = []
        for chunk in chunk_results:
            # 获取文件路径（使用辅助方法处理空值）
            file_urls = self._get_file_urls_from_child(chunk)

            retrival_info.append(
                {
                    "chunk_content": chunk.get("chunk_content"),
                    "recall_index": chunk.get("rerank_index") if "rerank_index" in chunk else chunk.get("recall_index"),
                    "recall_score": chunk.get("rerank_score") if "rerank_score" in chunk else chunk.get("recall_score"),
                    "reference_file": chunk.get("file_name"),
                    "reference_node": chunk.get("reference_node", []),
                    "file_urls": file_urls,
                    "page": chunk.get("page"),
                    "row": chunk.get("row"),
                    "reference_chunk_id": chunk.get("number"),
                    "reference_kb_name": kb_name,
                    "reference_kb_id": self.request.retrival_params.id,
                    "convert_path": chunk.get("convert_path", ""),
                    "remove_image_path": chunk.get("remove_image_path", ""),
                    "file_id": chunk.get("file_id", ""),
                    "chunk_id": chunk.get("chunk_id", ""),
                    "child_docs": [
                        {
                            "chunk_content": (
                                child.get("chunk_content")
                                if "chunk_content" in child
                                else child.get("entity", {}).get("content", "")
                            ),
                            "recall_index": child.get("rerank_index", child.get("recall_index", 0)),
                            "recall_score": child.get(
                                "rerank_score", child.get("recall_score", child.get("distance", 0))
                            ),
                            "reference_file": (
                                child.get("file_name")
                                if "file_name" in child
                                else child.get("entity", {}).get("file_name", "")
                            ),
                            "reference_node": child.get(
                                "reference_node", child.get("entity", {}).get("source_data", [])
                            ),
                            "file_urls": (
                                (child.get("file_urls"))
                                if child.get("file_urls", "").endswith(".pdf")
                                else MongodbUtil.query_doc_by_id(
                                    collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                                    doc_id=(
                                        child.get("file_id")
                                        if "file_id" in child
                                        else child.get("entity", {}).get("file_id")
                                    ),
                                ).get("pdf_path", child.get("file_urls", child.get("entity", {}).get("file_urls", "")))
                            ),
                            "page": child.get("page", []),
                            "row": child.get("row", []),
                            "reference_chunk_id": child.get("number", child.get("entity", {}).get("number")),
                            "reference_kb_name": kb_name,
                            "reference_kb_id": self.request.retrival_params.id,
                            "convert_path": child.get("convert_path", ""),
                            "remove_image_path": child.get("remove_image_path", ""),
                            "file_id": child.get("file_id", child.get("entity", {}).get("file_id", "")),
                            "child_docs": child.get("child_docs", []),
                        }
                        for child in chunk.get("child_docs", [])
                    ],
                }
            )

        # 拼接 chunk_content
        if self.request.model_uid in model_list and citation_open == 1:  # 溯源切片加引用编号
            chunk_content = self._build_chunk_content_with_images(chunk_results)
            chunk_content = self._build_chunk_content(chunk_content)
        else:
            chunk_content = self._build_chunk_content_with_images(chunk_results)
            new_list = [item["chunk_content"] for item in chunk_content if "chunk_content" in item]
            chunk_content = new_list

        return retrival_info, chunk_content

    async def web_search_and_build_chunk(
        self,
        db,
        user_query: str,
        model_list: list,
        citation_open: int,
        kb_retrival_info: list,
    ):
        count: int = 10
        max_items: int = 8
        bocha_result = {}
        logger.info("联网搜索中...")
        try:
            bocha_result = await BochaService.web_search(
                db=db,
                query=user_query,
                freshness="noLimit",
                summary=True,
                include=None,
                exclude=None,
                count=count,
            )
            logger.info("联网搜索成功 | query={} | count={}", user_query, count)
        except Exception as e:
            logger.exception(f"博查API搜索失败: {str(e)}")

        results = []
        if isinstance(bocha_result, dict):
            search_data = bocha_result.get("data")
            # logger.info("bocha_result_data: {}", search_data)
            web_results = search_data.get("webPages") if isinstance(search_data, dict) else {}
            results = web_results.get("value", []) if isinstance(web_results, dict) else []
        # logger.info("web搜索结果: {}", results)

        web_retrival_info = []
        chunk_items = []
        start_idx = len(kb_retrival_info) + 1
        for idx, item in enumerate(results[:max_items], start=start_idx):
            title = item.get("name") or ""
            url = item.get("url") or ""
            snippet = item.get("snippet") or ""
            summary = item.get("summary") or ""
            siteIcon = item.get("siteIcon") or ""
            if not snippet:
                continue
            web_retrival_info.append(
                {"reference_title": title, "web_url": url, "snippet": snippet, "summary": summary, "siteIcon": siteIcon, "type": "web_search"}
            )
            if self.request.model_uid in model_list and citation_open == 1:
                chunk_items.append(f"引用编号：[{idx}] {title}\nURL: {url}\n{summary}")
            else:
                chunk_items = [item_["summary"] for item_ in web_retrival_info if "summary" in item_]
        web_chunk_content = "\n\n".join(chunk_items)
        # logger.info("web_chunk_content: {}", web_chunk_content)

        return web_retrival_info, web_chunk_content

    async def process_v1(self, db, model_list, citation_open):
        if self.request.retrival_params.id != "":
            try:
                # 1. 获取知识库名称
                kb_doc = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(self.request.retrival_params.id)
                )
                kb_name = kb_doc.get("kb_name", "未知知识库")
                team_code = kb_doc.get("team_code", "")
                account_id = kb_doc["account_id"]
                rewrite_query = None
                # 复制一份检索参数，避免修改原始请求参数
                if self.request.is_question_rewriting:  # 为true,问题改写
                    # logger.info("问题改写")
                    retrival_params_tmp = copy.deepcopy(self.request.retrival_params)
                    # openAILLMService = OpenAILLMService(id=self.request.id)
                    # retrival_params_tmp.user_query = openAILLMService.rewrite_question(
                    #     db=db, request=self.request, retrival_params=retrival_params_tmp, type=None
                    # )
                    # logger.info(f"问题改写后的问题{retrival_params_tmp.user_query}")
                    # 同义词扩展
                    logger.info("同义词扩展")
                    rewrite_query, retrival_params_tmp.user_query = await self.synonym_rewrite(
                        db, retrival_params_tmp.user_query, account_id, team_code
                    )
                    logger.info("同义词扩展后用户问题：{}", rewrite_query)

                    retrival_result = await self.knwolege_retrieval(retrival_params_tmp)
                    retrival_result = json.loads(retrival_result.body)

                else:
                    logger.info("无问题改写")
                    retrival_result = await self.knwolege_retrieval(self.request.retrival_params)
                    retrival_result = json.loads(retrival_result.body)
                    rewrite_query = self.request.retrival_params.user_query  # 用户原问题

                # 3. 提取检索结果
                chunk_results = retrival_result.get("data", {}).get("results", [])
                logger.info("知识库检索完成 | kb={} | 结果数量={}", kb_name, len(chunk_results))

                # 4. 整理检索信息
                retrival_info = []
                for chunk in chunk_results:
                    file_urls = ""
                    if chunk.get("file_urls", "").endswith(".pdf"):
                        file_urls = chunk.get("file_urls")
                    else:
                        file_doc = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, doc_id=chunk.get("file_id")
                        )
                        file_urls = file_doc.get("pdf_path", chunk.get("file_urls", ""))

                    retrival_info.append(
                        {
                            "chunk_content": chunk.get("chunk_content", ""),
                            "recall_index": chunk.get("rerank_index", chunk.get("recall_index")),
                            "recall_score": chunk.get("rerank_score", chunk.get("recall_score")),
                            "reference_file": chunk.get("file_name", ""),
                            "reference_node": chunk.get("reference_node", []),
                            "file_urls": file_urls,
                            "page": chunk.get("page"),
                            "row": chunk.get("row"),
                            "reference_chunk_id": chunk.get("number"),
                            "reference_kb_name": kb_name,
                            "reference_kb_id": self.request.retrival_params.id,
                            "convert_path": chunk.get("convert_path", ""),
                            "remove_image_path": chunk.get("remove_image_path", ""),
                            "file_id": chunk.get("file_id", ""),
                            "chunk_id": chunk.get("chunk_id", ""),
                            "child_docs": [
                                {
                                    "chunk_content": (
                                        child.get("chunk_content")
                                        if "chunk_content" in child
                                        else child.get("entity", {}).get("content", "")
                                    ),
                                    "recall_index": child.get("rerank_index", child.get("recall_index", 0)),
                                    "recall_score": int(
                                        child.get(
                                            "distance",
                                            child.get("entity", {}).get("distance", child.get("distance", 0)),
                                        )
                                        * 100
                                    )
                                    / 100.0,
                                    "reference_file": (
                                        child.get("file_name")
                                        if "file_name" in child
                                        else child.get("entity", {}).get("file_name", "")
                                    ),
                                    "reference_node": child.get(
                                        "reference_node", child.get("entity", {}).get("source_data", [])
                                    ),
                                    "file_urls": self._get_file_urls_from_child(child),
                                    "page": child.get("page", []),
                                    "row": child.get("row", []),
                                    "reference_chunk_id": child.get("number", child.get("entity", {}).get("number")),
                                    "reference_kb_name": kb_name,
                                    "reference_kb_id": self.request.retrival_params.id,
                                    "convert_path": child.get("convert_path", ""),
                                    "remove_image_path": child.get("remove_image_path", ""),
                                    "file_id": child.get("file_id", child.get("entity", {}).get("file_id", "")),
                                    "child_docs": child.get("child_docs", []),
                                }
                                for child in chunk.get("child_docs", [])
                            ],
                        }
                    )

                # 5. 拼接chunk内容
                try:
                    # 尝试执行构建chunk内容的操作
                    if self.request.model_uid in model_list and citation_open == 1:  # 溯源切片加引用编号
                        chunk_content = self._build_chunk_content_with_images(chunk_results)
                        chunk_content = self._build_chunk_content(chunk_content)
                    else:
                        chunk_content = self._build_chunk_content_with_images(chunk_results)
                        new_list = [item["chunk_content"] for item in chunk_content if "chunk_content" in item]
                        chunk_content = new_list

                except Exception as e:
                    # 捕获所有可能的异常并处理
                    logger.exception(f"构建chunk内容时发生错误: {str(e)}")

                stream_type = 0  # 挂载知识库type=0

            except Exception as e:
                logger.exception(f"知识库检索失败: {e}")
                retrival_info = []
                chunk_content = ""
                stream_type = 1

        else:
            logger.info("未挂载知识库检索")
            rewrite_query=None
            retrival_info = []
            chunk_content = ""
            stream_type = 3  # 未挂载知识库type=3

        return chunk_content, stream_type, retrival_info, rewrite_query

    @staticmethod
    def _build_chunk_content(chunk_results):
        """构建 chunk_content 字符串"""
        if not chunk_results:
            return ""

        concatenated_result = []
        for index, chunk in enumerate(chunk_results, start=1):
            file_url = chunk.get("file_urls", "")
            file_name = file_url.split("/")[1]
            # number = chunk.get("number", "")
            chunk_result = chunk.get("chunk_content", "")
            formatted = f"引用编号：[{index}]\n{file_name}内容为[{chunk_result}]"
            concatenated_result.append(formatted)

        return "\n\n".join(concatenated_result)

    async def synonym_rewrite(self, db, query: str, account_id: str, team_code: str):
        """
        对查询语句进行同义词改写
        返回：改写后的查询语句和同义词结构
        """
        synonym_ids = set(self.request.synonym or [])
        rewrite_main_words = []

        # 获取管理员账号ID + 当前账号
        _, admin_ids = await ModelFamilyService.get_account_id_by_user_attribute(db, 1, None)
        admin_ids.append(account_id)

        # Step 1. 获取候选同义词组
        base_groups = (
            db.query(SynonymGroupModel)
            .filter(
                SynonymGroupModel.created_by.in_(admin_ids),
                SynonymGroupModel.group_type == "0",
                SynonymGroupModel.status == "0",
                SynonymGroupModel.is_deleted == False,
            )
            .order_by(SynonymGroupModel.created_time.asc())
            .all()
        )

        # Step 2. 收集符合条件的同义词组ID
        for group in base_groups:
            synonym_id = None

            if group.created_by == account_id:
                is_attribute = await ModelFamilyService.get_user_attribute_by_account_id(db, account_id)
                if is_attribute:
                    synonym_id = group.id
                elif team_code:
                    team_groups = (
                        db.query(SynonymGroupModel)
                        .filter(
                            SynonymGroupModel.is_deleted == False,
                            SynonymGroupModel.team_code == team_code,
                            SynonymGroupModel.group_type == "0",
                            SynonymGroupModel.status == "0",
                        )
                        .all()
                    )
                    synonym_ids.update([g.id for g in team_groups])
                elif not group.team_code:
                    synonym_id = group.id
            else:
                synonym_id = group.id

            if synonym_id:
                synonym_ids.add(synonym_id)

        team_groups = (
            db.query(SynonymGroupModel)
            .filter(
                SynonymGroupModel.is_deleted == False,
                SynonymGroupModel.team_code == team_code,
                SynonymGroupModel.group_type == "0",
                SynonymGroupModel.status == "0",
            )
            .all()
        )
        synonym_ids.update([g.id for g in team_groups])

        # Step 3. 获取去重且排序后的同义词组
        ordered_synonym_ids = [
            g.id
            for g in db.query(SynonymGroupModel)
            .filter(SynonymGroupModel.id.in_(synonym_ids), SynonymGroupModel.status == "0")
            .order_by(SynonymGroupModel.created_time.asc())
            .all()
        ]

        # Step 4. 构建 rewrite_main_words
        for group_id in ordered_synonym_ids:
            main_words = SynonymGroupService.get_main_words_with_synonyms(
                db=db, group_id=group_id, main_word_status="0"
            )
            for mw in main_words:
                synonyms = [s["synonym"] for s in mw.get("synonyms", [])]
                if not synonyms:
                    continue

                # 若 query 中包含任意同义词，则记录该组
                matched = [s for s in synonyms if s in query]
                if matched:
                    rewrite_main_words.append({"rewrite_word": matched[0], "all_synonyms": synonyms})

        # Step 5. 去除 all_synonyms 列表有交集的前项
        to_remove = set()
        for i, item_i in enumerate(rewrite_main_words):
            set_i = set(item_i["all_synonyms"])
            for j, item_j in enumerate(rewrite_main_words[i + 1 :], start=i + 1):
                if set_i & set(item_j["all_synonyms"]):
                    to_remove.add(i)
                    break
        rewrite_main_words = [item for idx, item in enumerate(rewrite_main_words) if idx not in to_remove]

        # Step 6. 合并重复 rewrite_word
        merged = {}
        for item in rewrite_main_words:
            rw, syns = item["rewrite_word"], set(item["all_synonyms"])
            merged[rw] = list(set(merged.get(rw, [])) | syns)
        final_rewrite_main_words = [{"rewrite_word": k, "all_synonyms": v} for k, v in merged.items()]

        # Step 7. 改写 query 文本
        # 初始化检索用的改写文本，避免无匹配时未赋值
        retrieval_query = query
        for item in final_rewrite_main_words:
            rw, all_synonyms = item["rewrite_word"], list(dict.fromkeys(item["all_synonyms"]))
            others = [s for s in all_synonyms if s != rw]
            if rw in query and others:
                synonyms_str = f"{'，'.join(others)}"
                synonyms_strs = f"{rw}（即{synonyms_str}，注意已经明确这几个名称指的是同一个实体，回答输出时不要输出这些别称，只输出{rw}）"
                retrieval_str = f"{rw}（即{synonyms_str}）"
                query = query.replace(rw, synonyms_strs)
                retrieval_query = retrieval_query.replace(rw, retrieval_str)
        # 返回一个给大模型的问题、一个给知识库检索的问题
        return query, retrieval_query

class ChatAgent_tools_Service:
    def __init__(self, request, knwolege_retrieval):
        self.request = request
        self.knwolege_retrieval = knwolege_retrieval

    def build_agent(self, db, user_query: str, model_list: list, citation_open: int):
        @tool("联网搜索")
        async def web_search_tool(query: str, freshness: str = "noLimit", count: int = 8) -> str:
            """根据查询词进行网络搜索，返回包含title/url/summary的JSON字符串。"""
            try:
                logger.info("Agent调用联网搜索工具...")
                query = user_query
                logger.info("联网搜索的搜索问题:{}", query)
                result = await BochaService.web_search(
                    db=db,
                    query=query,
                    freshness=freshness,
                    summary=True,
                    include=None,
                    exclude=None,
                    count=count,
                )
                # logger.info("联网搜索工具返回结果:{}", result)
                if isinstance(result, dict):
                    data = result.get("data")
                return json.dumps({"results": data}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"web_search失败: {str(e)}"}, ensure_ascii=False)

        @tool("知识库检索")
        async def knowledge_search_tool(query: str) -> str:
            """执行知识库检索，返回kb_results与chunk_content的JSON字符串。"""
            try:
                logger.info("Agent调用知识库检索...")
                KnowledgeRetrieval = KnowledgeRetrievalLLMQA(self.request, self.knwolege_retrieval)
                retrival_info2, chunk_content2 = await KnowledgeRetrieval.process_v1_file(model_list, citation_open)
                for sub in retrival_info2:
                    docs_index = []
                    for sub_doc in sub.get("child_docs", []):
                        try:
                            docs_index.append(int(sub_doc.get("reference_chunk_id")))
                        except Exception:
                            pass
                    sub["child_docs"] = docs_index
                # if isinstance(top_k, int) and top_k > 0:
                #     retrival_info2 = retrival_info2[:top_k]
                return json.dumps({"kb_results": retrival_info2, "chunk_content": chunk_content2}, ensure_ascii=False)
            except Exception as e:
                return json.dumps({"error": f"knowledge_retrieval失败: {str(e)}"}, ensure_ascii=False)

        tools = [web_search_tool, knowledge_search_tool]
        result = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(self.request.id)
        )
        if result and result.get("is_external") == True:
            llm = ChatOpenAI(
                model=self.request.model_uid,
                temperature=self.request.temperature,
                max_tokens=self.request.max_token_length,
                api_key=result["api_key"],
                base_url=result["api_url"],
                streaming=False,
            )
        else:
            llm = ChatOpenAI(
                model=self.request.model_uid,
                temperature=self.request.temperature,
                max_tokens=self.request.max_token_length,
                api_key=ModelConfig.LLM_API_KEY,
                base_url=ModelConfig.LLM_API_BASE,
                streaming=False,
            )
        system_prompt = (
            "你是一个可以使用工具的助理。收到非空输入后，先进行‘知识库检索’，根据检索命中的相关性和用户的输入判断是否需要再调用‘联网搜索’以补充最新信息；"
            "调用任何工具时，query参数必须严格等于用户输入；如两者皆用，完成检索后再整合回答，并在末尾列出引用标题与URL。用户问题为{}".format(user_query)
        )
        agent = create_agent(model=llm, tools=tools, system_prompt=system_prompt)
        return agent

    @staticmethod
    def parse_agent_retrival_info(result):
        try:
            messages = result.get("messages", []) if isinstance(result, dict) else []
            kb_results = []
            kb_chunk = ""
            web_results = []
            for msg in messages:
                name = getattr(msg, "name", None)
                content = getattr(msg, "content", None)
                if name == "联网搜索" and isinstance(content, str):
                    import json as _json
                    try:
                        payload = _json.loads(content)
                        results = []
                        top_res = payload.get("results")
                        if isinstance(top_res, dict):
                            res_web = top_res.get("webPages") or {}
                            if isinstance(res_web, dict) and isinstance(res_web.get("value"), list):
                                results = res_web.get("value", [])
                            elif isinstance(top_res.get("value"), list):
                                results = top_res.get("value", [])
                        for it in results:
                            web_results.append(
                                {
                                    "name": it.get("name") or it.get("title") or "",
                                    "url": it.get("url") or it.get("displayUrl") or it.get("link") or "",
                                    "snippet": it.get("snippet") or "",
                                    "summary": it.get("summary") or it.get("content") or "",
                                    "siteIcon": it.get("siteIcon") or "",
                                }
                            )
                    except Exception:
                        pass
                if name == "知识库检索" and isinstance(content, str):
                    import json as _json
                    try:
                        payload = _json.loads(content)
                        kb_res = payload.get("kb_results")
                        if isinstance(kb_res, list):
                            kb_results.extend(kb_res)
                        if isinstance(payload.get("chunk_content"), str):
                            kb_chunk = payload.get("chunk_content")
                    except Exception:
                        pass
            return {"kb_results": kb_results, "kb_chunk": kb_chunk, "web_results": web_results}
        except Exception:
            return {"kb_results": [], "kb_chunk": "", "web_results": []}
