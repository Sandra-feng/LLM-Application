from typing import List
from pydantic import BaseModel, Field


class RerankModelTestRequestEntity(BaseModel):

    kb_name: str = Field(..., examples=["tiance_test"], description="知识库名字")
    rerank_model: str = Field(
        ..., examples=["bge-reranker-large"], description="用户需要测试的重排模型"
    )

    user_query: str = Field(..., examples=["个人信息保护"], description="用户查询")
    top_n: int = Field(..., examples=[3], description="重排召回个数")


class RerankModelTestResponseEntity(BaseModel):
    user_query: str = Field(..., examples=["个人信息保护"], description="用户问题")
    results: List = Field(..., description="重排返回的结果")
