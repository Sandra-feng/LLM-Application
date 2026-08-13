# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：embedding_test_entity.py
@Author  ：JianbinLi
@Date    ：2024/09/02 17:14
"""

from typing import List
from pydantic import BaseModel, Field


class EmbeddingModelTestRequestEntity(BaseModel):

    kb_name: str = Field(..., examples=["py_test"], description="知识库名字")
    embedding_model: str = Field(
        ..., examples=["bge-large-zh-v1.5"], description="用户需要测试的嵌入模型"
    )

    user_query: str = Field(..., examples=["实验室考勤规则"], description="用户查询")
    top_n: int = Field(..., examples=[3], description="嵌入召回个数")


class EmbeddingEvaluationRequestParams(BaseModel):
    """
    定义了向量模型评估请求所需的参数，包括模型UID、查询字符串、召回文本数量及知识库ID。

    Attributes:
        model_uid (str): 向量模型的唯一标识符，默认为 'bge-base-zh-v1.5'。
        query (str): 用户输入的查询字符串，用于召回相关文本块，此字段为必填。
        limit (int): 需要召回的文本块数量，默认为 3。
        knowledge_base_id (str): 知识库的唯一标识符，此字段为必填。
    """

    model_uid: str = Field("bge-base-zh-v1.5", description="向量模型UID")
    query: str = Field(..., description="用户输入的查询, 用于召回文本块")
    limit: int = Field(3, description="召回文本块个数")
    kb_name: str = Field(..., description="知识库ID")


class EmbeddingModelTestResponseEntity(BaseModel):
    user_query: str = Field(..., examples=["个人信息保护"], description="用户问题")
    results: List = Field(..., description="重排返回的结果")
