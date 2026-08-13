# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：embedding_model_api.py
@Author  ：JianbinLi
@Date    ：2024/08/27 16:48
"""

from loguru import logger
from fastapi import APIRouter, Body
from fastapi.responses import Response

from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.embedding_util import EmbeddingUtil
from base_utils.milvus_util import MilvusUtil
from base_utils.mongodb_util import MongodbUtil
from base_utils.ret_util import RetUtil
from service_knowledge_manage.entity.knowledge_hub_entity import KnowledgeRecallEntity
from service_model_manage.entity.embedding_evaluation_entity import (
    EmbeddingEvaluationRequestParams,
    EmbeddingModelTestRequestEntity,
    EmbeddingModelTestResponseEntity,
)
from service_model_manage.service.embedding_service import OpenAIEmbeddingMilvusService, OpenAIEmbeddingService
# logger = loguru logger (auto-migrated)
router = APIRouter()





# @router.post(
#     "/aget_relevant_documents",
#     summary="查询相关文档",
# )
# async def aget_relevant_documents(
#     request: EmbeddingEvaluationRequestParams,
# ) -> Response:
#     try:
#         # 记录日志
#         logger.info("从知识库中召回文本chunks")
#
#         # 业务逻辑处理
#         openAIEmbeddingMilvusService = OpenAIEmbeddingMilvusService(model_uid=request.model_uid)
#
#         result_dict = openAIEmbeddingMilvusService.similarity_search_with_score(
#             query=request.query, limit=request.limit
#         )
#
#         if isinstance(result_dict, dict):
#             return result_dict
#         else:
#             logger.error("解析结果出现异常")
#             return RetUtil.response_error(message="解析结果出现异常")
#     except (Exception, RuntimeError) as e:
#         logger.error("向量获取异常:", exc_info=True)
#         return RetUtil.response_error(message="向量获取失败,请重试")


# @router.post(
#     "/get_embedding",
#     summary="获取向量表示",
# )
# async def aget_embedding(
#     model_uid: str = Body(..., description="模型ID"),
#     sentences: list = Body(..., description="句子列表"),
# ) -> Response:
#     """获取输入句子的嵌入
#
#     Args:
#         model_uid (str, optional): 模型ID.
#         sentences (list, optional): 句子列表.
#
#     Returns:
#         Response: 句子的向量表示列表
#     """
#     try:
#         # 记录日志
#         logger.info("获取句子的向量表示")
#         # 业务逻辑处理
#         openAIEmbeddingService = OpenAIEmbeddingService(model_uid=model_uid)
#         embeddings = openAIEmbeddingService.get_embedding(sentences=sentences)
#         return RetUtil.response_ok(data=embeddings)
#     except (Exception, RuntimeError) as e:
#         logger.error("句子的向量表示获取异常:", exc_info=True)
#         return RetUtil.response_error(message="向量获取失败,请重试")


# @router.post(
#     "/embedding_model_test",
#     summary="嵌入模型测试",
#     response_model=EmbeddingModelTestResponseEntity,
# )
# async def embedding_model_test(
#     params: EmbeddingModelTestRequestEntity,
# ) -> Response:
#     logger.info(f"嵌入模型测试，参数--：{params}")
#     try:
#         # 连接MongoDB数据库
#         MongodbUtil.connect()
#         query_result = MongodbUtil.query_docs_by_condition(
#             collection_name=CollectionConfig.KB_COLLECTION, search_condition={"kb_name": params.kb_name}
#         )
#         embedding_model = ModelConfig.DEFAULT_EMBEDDING_MODEL
#         for item in query_result:
#             if item:
#                 embedding_model = item["embedding_model"]
#             else:
#                 raise ValueError("知识库不存在")
#
#         # 获取向量embedding工具
#         embeddingUtil = EmbeddingUtil()
#         embeddings = embeddingUtil.get_embedding(model_uid=embedding_model, input=params.user_query)
#
#         # 获取milvus工具
#         milvusUtil = MilvusUtil()
#         docs = milvusUtil.search_by_vector(collection_name=params.kb_name, vector=embeddings, limit=params.top_n)[0]
#
#         if len(docs) == 0:
#             data = EmbeddingModelTestResponseEntity(user_query=params.user_query, results=chunks)
#             return RetUtil.response_ok(data=data.model_dump())
#
#         # 解析输出
#         chunks = []
#         for index, item in enumerate(docs, start=1):
#             chunk = KnowledgeRecallEntity(
#                 recall_score=round(item["distance"], 2),
#                 recall_index=index,
#                 chunk_content=item["entity"]["content"],
#                 file_name=item["entity"]["file_name"],
#                 number=item["entity"]["number"],
#             )
#             chunks.append(chunk)
#
#         data = EmbeddingModelTestResponseEntity(user_query=params.user_query, results=chunks)
#         return RetUtil.response_ok(data=data.model_dump())
#
#     except (Exception, RuntimeError) as e:
#         return RetUtil.response_error(message="向量获取失败,请重试")