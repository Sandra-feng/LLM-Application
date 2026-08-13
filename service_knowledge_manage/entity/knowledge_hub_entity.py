
from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeRetrivalInfo(BaseModel):
    """
    检索入参
    """

    id: Optional[str] = Field("", examples=["tiance_test"], description="知识库id")
    kb_name: Optional[str] = Field("", examples=["tiance_test"], description="知识库名称")
    user_query: str = Field(..., examples=["个人信息保护"], description="用户问题")

    rerank_model: Optional[str] = Field("", examples=["bge-reranker-large"], description="重排模型模型名称，由用户选择")
    rerank_id: Optional[str] = Field("", examples=["67e4f62c3119180a08d363aa"], description="重排模型id")
    rerank_num: Optional[int] = Field(0, examples=[3], description="重排返回数量")

    recall_num: int = Field(0, examples=[10], description="向量召回个数")
    score: float = Field(0.1, examples=[0.1], description="阈值")
    enhance_rounds: Optional[int] = Field(0, examples=[3], description="增强轮数")
    filter: Optional[str] = Field(
        "", examples=["file_name like '%文档1%' or file_name like '%文档2%'"], description="文件过滤条件"
    )

    # 混合检索配置参数
    search_type: str = Field(
        "semantic",
        examples=["semantic"],
        description="检索类型: semantic(语义检索), fulltext(全文检索), hybrid(混合检索)",
    )
    fusion_weights: Optional[list[float]] = Field(
        [0.7, 0.3],
        examples=[[0.7, 0.3]],
        description="加权融合权重 [稠密向量权重, 全文搜索权重]",
    )


class KnowledgeRecallEntity(BaseModel):
    chunk_content: str = Field(..., examples=[""], description="切片内容")

    number: int = Field(..., examples=[1], description="文本chunk的切块序号")
    file_name: str = Field("", examples=["test.xlsx"], description="源文件名")
    page: list = Field([], examples=[[]], description="切片的文件页码")
    row: list = Field([], examples=[[]], description="切片的文件页码")
    file_id: str = Field([], examples=[[]], description="切片的文件路径")
    file_urls: str = Field([], examples=[[]], description="切片的文件路径")

    recall_score: float = Field(..., examples=[0.1], description="向量召回分数")
    recall_index: int = Field(..., examples=[1], description="向量召回排名")

    reference_node: list = Field([], examples=[[]], description="切片的图片位置")

    convert_path: str = Field("", examples=["test.xlsx"], description="文件路径")
    remove_image_path: str = Field("", examples=["test.xlsx"], description="文件路径")
    child_docs: Optional[list] = Field(None, examples=[[]], description="子块信息（仅父块有此字段）")
    chunk_id: Optional[str] = Field(..., examples=[""], description="切片chunkid")


class KnowledgeEntity(BaseModel):
    chunk_content: str = Field(..., examples=[""], description="切片内容")

    number: int = Field(..., examples=[1], description="文本chunk的切块序号")
    file_name: str = Field("", examples=["test.xlsx"], description="源文件名")
    file_urls: str = Field([], examples=[[]], description="切片的文件路径")
    page: list = Field([], examples=[[]], description="切片的文件页码")
    file_id: str = Field([], examples=[[]], description="切片的文件路径")
    row: list = Field([], examples=[[]], description="切片的文件页码")

    recall_score: float = Field(..., examples=[0.1], description="向量召回分数")
    recall_index: int = Field(..., examples=[1], description="向量召回排名")

    rerank_score: float = Field(None, examples=[0.9], description="重排分数")
    rerank_index: int = Field(None, examples=[1], description="重排排名")

    reference_node: list = Field([], examples=[[]], description="切片的图片位置")
    child_docs: Optional[list] = Field(None, examples=[[]], description="子块信息（仅父块有此字段）")
    chunk_id: Optional[str] = Field(..., examples=[""], description="切片chunkid")


class KnowledgeRetrivalResponse(BaseModel):
    is_rerank: bool = Field(..., examples=[True], description="是否重排")
    user_query: str = Field(..., examples=["个人信息保护"], description="用户问题")
    results: list = Field(..., examples=["检索结果，向量召回结果或者重排召回结果"])


class KnowledgeDialogInfo(BaseModel):
    model_uid: str = Field(..., examples=["qwen1.5-7B-chat"], description="模型UID")
    retrival_params: KnowledgeRetrivalInfo = Field(..., description="知识库检索参数")
    chatbot: list[dict] = Field([], description="对话记录")
    history: Optional[int] = Field(3, examples=[3], description="对话历史轮数")
    max_token_length: Optional[int] = Field(4096, examples=[4096], description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, examples=[0.8], description="温度参数")
