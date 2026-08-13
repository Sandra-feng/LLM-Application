#!/usr/bin/env python
"""
知识库检索工具 - 基于 @tool 装饰器的函数式设计
将知识库检索功能封装为 LangChain Tool
"""

import json
from typing import Any, Optional

from langchain.tools import tool
from loguru import logger
from pydantic import ConfigDict, BaseModel, Field


class KnowledgeBaseConfig(BaseModel):
    """知识库配置"""

    id: str = Field(..., description="知识库 ID")
    kb_name: str = Field(..., description="知识库名称")
    rerank_model: str = Field(default="", description="重排序模型")
    rerank_id: str = Field(default="", description="重排序模型 ID")
    recall_num: int = Field(default=10, description="召回数量")
    rerank_num: int = Field(default=3, description="重排序数量")
    score: float = Field(default=0.1, description="相似度阈值")
    enhance_rounds: int = Field(default=0, description="增强轮次")
    search_type: str = Field(default="semantic", description="搜索类型")
    fusion_weights: Optional[list[float]] = Field(default=None, description="融合权重")


class KnowledgeRetrieverConfig(BaseModel):
    """知识库检索器配置"""

    kb_configs: list[KnowledgeBaseConfig] = Field(..., description="知识库配置列表")
    recall_setting: dict = Field(..., description="召回设置")
    enable_synonym: bool = Field(default=False, description="是否启用同义词扩展")
    synonym_list: list = Field(default_factory=list, description="同义词列表")
    db: Any = Field(None, description="数据库会话")
    account_id: str = Field("", description="账户 ID")
    team_code: str = Field("", description="团队代码")
    model_config = ConfigDict(arbitrary_types_allowed=True)


async def _retrieve_knowledge(
    query: str,
    config: KnowledgeRetrieverConfig,
) -> dict[str, Any]:
    """
    执行知识库检索

    Args:
        query: 用户查询
        config: 检索器配置

    Returns:
        检索结果字典
    """
    from types import SimpleNamespace

    from service_knowledge_manage.api.routes.knowledge_hub_route import knwolege_retrieval
    from service_knowledge_manage.entity.knowledge_hub_entity import KnowledgeRetrivalInfo
    from service_model_manage.service.QAKnowledgeRetrieval import KnowledgeRetrievalLLMQA

    logger.info(f"知识库检索工具被调用 | 查询: {query}")

    # 处理同义词扩展
    retrieval_query = query
    rewrite_query = ""

    if config.enable_synonym and config.synonym_list:
        logger.info("执行同义词扩展")
        synonym = SimpleNamespace(synonym=config.synonym_list)
        knowledge_retrieval_qa = KnowledgeRetrievalLLMQA(synonym, {})
        rewrite_query, retrieval_query = await knowledge_retrieval_qa.synonym_rewrite(
            config.db, query, config.account_id, config.team_code
        )
        logger.info(f"同义词扩展后查询: {retrieval_query}")

    # 执行知识库检索
    all_sources = []

    for kb in config.kb_configs:
        retrieval_params = KnowledgeRetrivalInfo(
            id=kb.id,
            kb_name=kb.kb_name,
            user_query=retrieval_query,
            rerank_model=kb.rerank_model,
            rerank_id=kb.rerank_id,
            recall_num=kb.recall_num,
            rerank_num=kb.rerank_num,
            score=kb.score,
            enhance_rounds=kb.enhance_rounds,
            search_type=kb.search_type,
            fusion_weights=kb.fusion_weights,
        )

        # 调用统一的检索方法
        response = await knwolege_retrieval(retrieval_params)

        if response.body.decode() and "code" in response.body.decode():
            response_data = json.loads(response.body.decode())
            if response_data.get("code") == 200:
                results = response_data.get("data", {}).get("results", [])

                for result in results:
                    # 处理子文档索引
                    docs_index = []
                    for sub_retrieval_info in result["child_docs"]:
                        sub_retrieval_info = sub_retrieval_info["entity"]
                        docs_index.append(int(sub_retrieval_info.get("number")))
                    result["child_docs"] = docs_index

                    # 构建统一的 source 数据结构
                    source_item = {
                        "chunk_content": result["chunk_content"],
                        "recall_score": result["recall_score"],
                        "reference_file": result["file_name"],
                        "reference_node": result["reference_node"],
                        "file_urls": result["file_urls"],
                        "reference_chunk_id": result["number"],
                        "page": result["page"],
                        "row": result["row"],
                        "recall_index": result["recall_index"],
                        "child_docs": result["child_docs"],
                        "reference_kb_id": kb.id,
                        "reference_kb_name": kb.kb_name,
                        "convert_path": result.get("convert_path", ""),
                        "remove_image_path": result.get("remove_image_path", ""),
                        "file_id": result.get("file_id", ""),
                    }
                    all_sources.append(source_item)

    # 后处理检索结果（重排序）
    if config.recall_setting.get("is_rerank") and all_sources:
        from base_utils.rerank_util import RerankUtil

        content = [item["chunk_content"] for item in all_sources]
        rerank_id = config.recall_setting["rerank_id"]
        rerank_model = config.recall_setting["rerank_model"]
        top_k = config.recall_setting["top_k"]

        rerank_results = RerankUtil(rerank_id=rerank_id).socre_rerank(
            model_uid=rerank_model,
            documents=content,
            query=query,
            top_n=top_k,
            return_documents=True,
            threshold=config.recall_setting.get("score", 0.1),
        )

        sorted_results = sorted(rerank_results, key=lambda x: x["relevance_score"], reverse=True)
        final_sources = []
        for result in sorted_results:
            source_item = all_sources[result["index"]]
            source_item["rerank_score"] = result["relevance_score"]
            source_item["rerank_index"] = result["index"]
            final_sources.append(source_item)
    else:
        # 按召回分数排序
        sorted_sources = sorted(all_sources, key=lambda x: x["recall_score"], reverse=True)
        recall_num = config.recall_setting.get("recall_num")
        if recall_num is not None:
            final_sources = sorted_sources[:recall_num]
        else:
            final_sources = sorted_sources

    # 格式化文档内容
    docs = ""
    docs_notrace = []
    if final_sources:
        all_docs_formatted = KnowledgeRetrievalLLMQA._build_chunk_content_with_images(final_sources)
        docs_notrace = [item["chunk_content"] for item in all_docs_formatted if "chunk_content" in item]
        docs = KnowledgeRetrievalLLMQA._build_chunk_content(all_docs_formatted)

    logger.info(f"知识库检索完成 | 检索到 {len(final_sources)} 条结果")

    return {
        "docs": docs,
        "sources": final_sources,
        "docs_notrace": docs_notrace,
        "retrieval_query": retrieval_query,
    }


def create_knowledge_tool(config: KnowledgeRetrieverConfig):
    """
    创建知识库检索工具

    使用 @tool 装饰器创建工具函数

    Args:
        config: 知识库检索器配置

    Returns:
        LangChain Tool 实例

    Example:
        >>> kb_config = KnowledgeBaseConfig(
        ...     id="kb_001",
        ...     kb_name="产品手册",
        ...     recall_num=10
        ... )
        >>> retriever_config = KnowledgeRetrieverConfig(
        ...     kb_configs=[kb_config],
        ...     recall_setting={"is_rerank": False}
        ... )
        >>> kb_tool = create_knowledge_tool(retriever_config)
    """

    @tool(
        "knowledge_retrieval",
        description="""检索知识库获取相关信息。当用户问题需要参考知识库中的专业知识、文档或数据时使用此工具。输入用户的问题，返回相关的知识片段。""",
    )
    async def knowledge_retrieval(query: str) -> dict[str, Any]:
        """
        知识库检索工具

        Args:
            query: 用户查询问题

        Returns:
            包含检索结果的字典，字段：
            - docs: 格式化的文档内容
            - sources: 知识库来源列表
            - docs_notrace: 不带溯源标记的文档内容
            - retrieval_query: 实际检索查询（可能经过同义词扩展）
        """
        return await _retrieve_knowledge(query=query, config=config)

    return knowledge_retrieval


# ==================== 向后兼容包装器 ====================


class KnowledgeRetrieverTool:
    """
    知识库检索工具（向后兼容）

    保留旧的类接口，内部使用新的函数式工具
    """

    def __init__(
        self,
        kb_configs: list,
        recall_setting: dict,
        enable_synonym: bool = False,
        synonym_list: Optional[list] = None,
        db: Any = None,
        account_id: str = "",
        team_code: str = "",
    ):
        """初始化知识库检索工具"""
        # 转换为 Pydantic 模型
        kb_configs_typed = [KnowledgeBaseConfig(**kb) for kb in kb_configs]

        self.config = KnowledgeRetrieverConfig(
            kb_configs=kb_configs_typed,
            recall_setting=recall_setting,
            enable_synonym=enable_synonym,
            synonym_list=synonym_list or [],
            db=db,
            account_id=account_id,
            team_code=team_code,
        )

        # 创建实际工具
        self._tool = create_knowledge_tool(self.config)

    def __call__(self, *args, **kwargs):
        """使包装器可调用"""
        return self._tool(*args, **kwargs)

    @property
    def name(self) -> str:
        """工具名称"""
        return "knowledge_retrieval"

    @property
    def description(self) -> str:
        """工具描述"""
        return self._tool.description

    async def _arun(self, query: str) -> dict:
        """异步执行（向后兼容）"""
        return await self._tool.ainvoke({"query": query})

    def _run(self, query: str) -> dict:
        """同步执行（向后兼容）"""
        import asyncio

        return asyncio.run(self._arun(query))

    def as_tool(self):
        """返回 LangChain Tool 实例"""
        return self._tool
