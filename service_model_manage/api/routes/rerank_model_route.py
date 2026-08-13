# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：rerank_model_api.py
@Author  ：JianbinLi
@Date    ：2024/08/27 21:07
"""

import json
from loguru import logger
from typing import Any

from fastapi import APIRouter, Body, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import Response

from base_configs.mongodb_config import CollectionConfig
from base_utils.embedding_util import EmbeddingUtil
from base_utils.milvus_util import MilvusUtil
from base_utils.mongodb_util import MongodbUtil
from base_utils.rerank_util import RerankUtil
from base_utils.ret_util import RetUtil
from service_knowledge_manage.entity.knowledge_hub_entity import (
    KnowledgeEntity,
)
from service_model_manage.entity.rerank_entity import (
    RerankModelTestRequestEntity,
    RerankModelTestResponseEntity,
)
from service_model_manage.service.model_supervise_service import ModelSuperviseService
from service_model_manage.service.rerank_service import XinferRerankService
# logger = loguru logger (auto-migrated)
router = APIRouter()


@router.post(
    "/get_running_rerank_model",
    summary="获取所有运行中的rerank模型",
)
async def aget_running_rerank_model() -> Response:
    """
    获取所有rerank模型

    返回:
    - running rerank 模型
    """
    # model_type: str = Body("rerank", description="模型类型，默认为rerank"),
    try:
        # 入口日志
        logger.info("->获取所有运行中的rerank模型 | params=%s", jsonable_encoder({}))

        # 业务逻辑处理
        rerank_model_results = await ModelSuperviseService.get_runing_rerank_models(model_type="rerank")

        return RetUtil.response_ok(data=rerank_model_results)

    except (Exception, RuntimeError) as e:
        logger.error("获取rerank模型失败", exc_info=True)
        return RetUtil.response_error(message="计算相关性分数失败,请重试")


# @router.post(
#     "/rerank_model_test",
#     summary="测试重排模型",
#     response_model=RerankModelTestResponseEntity,
# )
# async def arerank_model_test(params: RerankModelTestRequestEntity) -> Response:
#     logger.info("重排模型测试")
#     try:
#         # 连接MongoDB数据库
#         MongodbUtil.connect()
#
#         # 根据知识库的名称获取到embedding模型名称
#         query_result = MongodbUtil.query_docs_by_condition(
#             collection_name=CollectionConfig.KB_COLLECTION, search_condition={"kb_name": params.kb_name}
#         )
#         for result in query_result:
#             if result:
#                 embedding_model = result["embedding_model"]
#             else:
#                 logger.info("知识库不存在！！")
#                 raise ValueError("知识库不存在")
#
#         # query_result = MongodbUtil.query_doc_by_id(
#         #     collection_name=CollectionConfig.KB_COLLECTION, doc_id=params.kb_name
#         # )
#         # embedding_model = ModelConfig.DEFAULT_EMBEDDING_MODEL
#         # if query_result:
#         #     embedding_model = query_result["embedding_model"]
#         # else:
#         #     raise ValueError("知识库不存在")
#
#         # 获取向量embedding工具
#         embeddingUtil = EmbeddingUtil()
#         embeddings = embeddingUtil.get_embedding(model_uid=embedding_model, input=params.user_query)
#
#         # 获取milvus工具
#         milvusUtil = MilvusUtil()
#         docs = milvusUtil.search_by_vector(collection_name=params.kb_name, vector=embeddings, limit=25)[0]
#
#         if len(docs) == 0:
#             data = RerankModelTestResponseEntity(
#                 user_query=params.user_query,
#                 results=[],
#             )
#             return RetUtil.response_ok(data=data.model_dump())
#
#         # 解析输出
#         chunks = []
#         for index, item in enumerate(docs, start=1):
#             chunk = KnowledgeEntity(
#                 recall_score=round(item["distance"], 2),
#                 recall_index=index,
#                 chunk_content=item["entity"]["content"],
#                 file_name=item["entity"]["file_name"],
#                 rerank_score=0,
#                 rerank_index=0,
#                 number=item["entity"]["number"],
#             )
#             chunks.append(chunk)
#
#         def process_rerank_results(
#             docs: list[dict[str, Any]], rerank_results: list[dict[str, Any]]
#         ) -> list[dict[str, Any]]:
#             """
#             处理重排结果并将分数和顺序添加到原始数据结构中。
#
#             参数:
#             - original_data: List[Dict[str, Any]] 原始数据列表
#             - rerank_results: List[Dict[str, Any]] 重排函数返回的结果列表
#
#             返回:
#             - List[Dict[str, Any]] 更新后的数据列表
#             """
#
#             # 创建一个映射，用于快速查找原始数据
#             content_to_data = {item.chunk_content: item for item in docs}
#
#             # 按相关性分数排序重排结果
#             sorted_results = sorted(rerank_results, key=lambda x: x["relevance_score"], reverse=True)
#             # for item in sorted_results:
#             #     pprint(item)
#
#             # 处理重排结果
#             docs_only_contain_rerank = []
#             for rank, result in enumerate(sorted_results, start=1):
#                 content = result["document"]["text"]
#                 if content in content_to_data:
#                     # 更新原始数据
#                     content_to_data[content].rerank_score = result["relevance_score"]
#                     content_to_data[content].rerank_index = rank
#                     docs_only_contain_rerank.append(content_to_data[content])
#
#             # 返回更新后的数据列表
#             # return list(content_to_data.values())
#             return docs_only_contain_rerank
#
#         documents = [item.chunk_content for item in chunks]
#         query = params.user_query
#         top_n = params.top_n
#         model_uid = params.rerank_model
#         rerank_results = RerankUtil().rerank(
#             model_uid=model_uid,
#             documents=documents,
#             query=query,
#             top_n=top_n,
#             return_documents=True,
#         )
#         """
#         rerank_results的返回样式
#         [
#             {'document': {'text': '中国的主要节日包括春节、清明节、端午节和中秋节。春节是中国最重要的传统节日，家家户户都会庆祝。'},
#             'index': 0,
#             'relevance_score': 0.9988873600959778},
#
#             {'document': {'text': '春节通常在农历正月初一庆祝，是中国人团聚和庆祝新年的重要时刻。人们会吃饺子、放鞭炮，并进行各种传统活动。'},
#             'index': 1,
#             'relevance_score': 0.8788966536521912},
#
#             {'document': {'text': '端午节是为了纪念屈原的节日，人们通常在这一天吃粽子、赛龙舟。'},
#             'index': 4,
#             'relevance_score': 0.7846590876579285}
#         ]
#         """
#         docs_only_contain_rerank = process_rerank_results(chunks, rerank_results)
#         """
#         docs_only_contain_rerank的返回样式：
#         [   {'distance': 0.5920194387435913,
#             'entity': {'content': 'adfhgfdkgjfigsnfglij',
#                         'file_name': '《中国银保监会关于印发实施车险综合改革指导意见的通知》.pdf',
#                         'file_time': '2024-09-21 01:45:16',
#                         'number': 8},
#             'id': 452450913582844817,
#             'rerank_order': 1,
#             'rerank_score': 0.9909056425094604},
#             {'distance': 0.6637850999832153,
#             'entity': {'content': 'dsjklagdbfgjdlkfgjidsfnsdkgids',
#                         'file_name': '《中国银保监会关于印发实施车险综合改革指导意见的通知》.pdf',
#                         'file_time': '2024-09-21 01:45:16',
#                         'number': 9},
#             'id': 452450913582844818,
#             'rerank_order': 2,
#             'rerank_score': 0.982548177242279},
#
#             {'distance': 0.7208224534988403,
#             'entity': {'content': 'dsaklghdsjfidjgdskljk',
#                         'file_time': '2024-09-21 01:45:16',
#                         'number': 10},
#             'id': 452450913582844819,
#             'rerank_order': 3,
#             'rerank_score': 0.919082760810852}]
#         """
#         rerank_chunks = []
#         for item in docs_only_contain_rerank:
#             rerank_chunk = KnowledgeEntity(
#                 recall_score=round(item.recall_score, 2),
#                 recall_index=item.recall_index,
#                 chunk_content=item.chunk_content,
#                 file_name=item.file_name,
#                 rerank_score=round(item.rerank_score, 2),
#                 rerank_index=item.rerank_index,
#                 number=item.number,
#             )
#             rerank_chunks.append(rerank_chunk)
#
#         results = rerank_chunks
#         data = RerankModelTestResponseEntity(
#             user_query=params.user_query,
#             results=results,
#         )
#
#         return RetUtil.response_ok(data=data.model_dump())
#     except Exception as e:
#         detail = f"重排模型出错：{str(e)}"
#         logger.error(detail, exc_info=True)
#         # 返回HTTP错误响应
#         raise HTTPException(status_code=400, detail=detail)


@router.post(
    "/get_rerank_scores",
    summary="计算相关性分数",
)
async def aget_rerank_scores(
    model_uid: str = Body("bge-reranker-large", description="模型UID"),
    query: str = Body(..., description="用户查询"),
    top_n: int = Body(2, description="召回前2个"),
    sentences: list = Body(..., description="语句列表"),
) -> Response:
    print(f"sentences--{sentences}")
    """
    根据给定的模型UID、用户查询和语句列表，计算语句与查询之间的相关性分数。

    参数:
    - model_uid: 模型的唯一标识符，用于选择正确的模型来进行计算。
    - query: 用户的查询文本，用于与语句列表中的每个语句进行相关性比较。
    - sentences: 语句列表，这是一个包含多个语句的数组，每个语句都是一个字符串。

    返回:
    - 一个包含相关性分数的响应，分数表示每个语句与查询文本的相关性。
    """
    try:
        # 记录日志
        logger.info("计算query和语句列表的相关性分数")

        # 业务逻辑处理
        xinferRerankService = XinferRerankService()
        results = xinferRerankService.get_rerank_scores(
            model_uid=model_uid,
            query=query,
            documents=sentences,
            top_n=top_n,
            return_documents=True,
        )
        return RetUtil.response_ok(data=json.dumps({"results": results}))
    except (Exception, RuntimeError) as e:
        logger.error("计算相关性分数失败", exc_info=True)
        return RetUtil.response_error(message="计算相关性分数失败,请重试")
