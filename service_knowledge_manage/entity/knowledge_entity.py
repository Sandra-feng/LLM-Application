from sqlalchemy import Float
"""
@File         :knowledge_entity.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/03 15:14:54
"""

from typing import Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime,Text
from sqlalchemy import JSON
from sqlalchemy.dialects.mysql import MEDIUMTEXT


Base = declarative_base()
class KnowledgeInfo(BaseModel):
    kb_name: str = Field(..., examples=["test"], description="知识库名称")
    description: str = Field("", examples=["描述知识库"], description="知识库描述")
    embedding_model: str = Field(..., examples=["bge-large-zh-v1.5"], description="嵌入模型")
    embedding_dimension: int = Field(..., examples=[1024], description="嵌入维度")
    embedding_id: str = Field(..., examples=[""], description="嵌入模型id")
    rerank_id: str = Field("", examples=[""], description="重排模型id")
    team_code: Optional[str] = Field("", description="团队id", examples=["1"])
    embedding_max_tokens: int = Field(..., examples=[123], description="模型上下文长度")


class KnowledgeRetrievalSettingUpdate(BaseModel):
    """知识库检索设置更新实体"""

    id: str = Field(..., examples=["67e4f62c3119180a08d363aa"], description="知识库id")
    prompt: str = Field("", examples=[""], description="知识库名称")
    rerank_model: str = Field("", examples=["bge-reranker-large"], description="重排模型")
    retrieval_count: int = Field(10, examples=[10], description="检索返回文本数量")
    score: float = Field(0.5, examples=[0.5], description="召回阈值")
    top_k: int = Field(5, examples=[5], description="召回数量")
    rerank_id: str = Field(..., examples=["67e4f62c3119180a08d363aa"], description="重排模型的id")
    enhance_rounds: int = Field(..., examples=[3], description="检索增强轮数")
    search_type: str = Field(
        "semantic",
        examples=["semantic"],
        description="检索类型: semantic(语义检索), fulltext(全文检索), hybrid(混合检索)",
    )
    fusion_weights: list[float] = Field(
        [0.7, 0.3],
        examples=[[0.7, 0.3]],
        description="加权融合权重 [稠密向量权重, 全文搜索权重]",
    )


class RetrivalInfo(BaseModel):
    """
    知识库评测的检索入参
    """
    id: Optional[str] = Field("", examples=["tiance_test"], description="知识库id")
    kb_name: Optional[str] = Field("", examples=["tiance_test"], description="知识库名称")

    rerank_model: Optional[str] = Field("", examples=["bge-reranker-large"], description="重排模型模型名称，由用户选择")
    rerank_id: Optional[str] = Field("", examples=["67e4f62c3119180a08d363aa"], description="重排模型id")
    rerank_num: Optional[int] = Field(0, examples=[3], description="重排返回数量")
    is_rerank: Optional[bool] = Field(False, examples=[False], description="是否重排")

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
    semantics_weights: float = Field(0.7, examples=[0.7], description="语义检索权重")
    keywords_weights: float = Field(0.3, examples=[0.3], description="关键词检索权重")

class KnowledgeEvaluationRequest(BaseModel):
    """知识库评测请求实体"""
    # 评测文件的可下载URL（替代原先的 UploadFile 文件上传）
    file_url: str = Field(..., description="评测文件的可下载URL")
    retrival_params: RetrivalInfo = Field(default_factory=RetrivalInfo, description="知识库检索参数")
    knowledge_id: str = Field("", description="知识库id")
    similarity_threshold: float = Field(0.6, description="命中相似度阈值")
    task_name: str = Field("", description="任务名称")
    task_id: str = Field("", description="任务id")
    remote_path: str = Field("", description="文件远程路径")
    evaluation_id:  str = Field("", description="每次评测的id")

class KNOWLEDGE_EVALUATION(Base):
    __tablename__ = TableConfig.KNOWLEDGE_EVALUATION
    file_id = Column(String(100), primary_key=True, nullable=False, index=True)
    file_name = Column(String(100), nullable=True)
    file_url = Column(String(100), nullable=True)
    kb_id = Column(String(100), nullable=True)  # 知识库ID
    size = Column(Integer, nullable=True)  # 文件大小（字节）
    create_time = Column(DateTime, nullable=True)

# 注意：避免与 KNOWLEDGE_EVALUATION 重复定义同一表（knowledge_evaluation）

class KnowledgeEvaluationSetting(Base):
    """
    评测设置存储到 MySQL 的 config_info 表（使用 JSON 保存完整配置）
    """
    __tablename__ = TableConfig.KNOWLEDGE_EVALUATION_SETTING

    evaluation_id = Column(String(64), primary_key=True, index=True, nullable=False)
    file_id = Column(String(64), unique=True, index=True, nullable=False)
    evaluation_name = Column(String(64), index=True, nullable=False)
    similarity_threshold = Column(Float, default=0.0, nullable=False) # 命中相似度阈值
    search_type = Column(String(64), default="semantic", nullable=False) # 检索类型
    recall_num = Column(Integer, default=10, nullable=False) # 向量召回个数
    is_rerank = Column(Boolean, default=False, nullable=False) # 是否重排
    rerank_id = Column(String(64), nullable=True) # 重排模型id
    rerank_model = Column(String(64), nullable=True) # 重排模型名称
    rerank_num = Column(Integer, default=3, nullable=False) # 重排返回数量
    score = Column(Float, default=0.0, nullable=False) # 重排分数阈值
    needEnhanceRounds = Column(Boolean, default=False, nullable=False) # 是否检案増强
    enhance_rounds = Column(Integer, default=0, nullable=False) # 增强轮数
    semantics_weights = Column(Float, default=0.0, nullable=False) # 语义检索权重
    keywords_weights = Column(Float, default=0.0, nullable=False) # 关键词检索权重
    evaluation_num = Column(Integer, default=0, nullable=False) # 评测次数
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    # 评测状态：1-排队中, 2-评测中, 3-已完成, 4-失败
    status = Column(Integer, default=1, nullable=False)
    # 当 status=4 时保存失败原因
    message = Column(String(255), nullable=True)

class EvaluationQuestion(Base):
    """
    评测问题记录表：保存每次评测导入的题目与标准答案。
    """
    __tablename__ = TableConfig.EVALUATION_QUESTION

    # 使用外部生成的 question_id 作为主键，便于业务关联
    question_id = Column(String(64), primary_key=True, index=True, nullable=False)
    question_index = Column(Integer, default=0, nullable=False)
    file_id = Column(String(64), index=True, nullable=False)
    # 题目与标准答案可能较长，使用 MEDIUMTEXT
    question = Column(MEDIUMTEXT, nullable=False)
    standard_answer = Column(MEDIUMTEXT, nullable=False)
    create_time = Column(DateTime, nullable=False)


class EvaluationAnswer(Base):
    """
    评测答案记录表：逐条存储每个问题的检索块评估结果。
    """
    __tablename__ = TableConfig.EVALUATION_ANSWER

    answer_id = Column(String(64), primary_key=True, index=True, nullable=False)
    question_id = Column(String(64), index=True, nullable=False)
    evaluation_id = Column(String(64), index=True, nullable=False)

    chunk_content = Column(MEDIUMTEXT, nullable=False)
    recall_score = Column(Float, default=0.0, nullable=False)
    is_hit = Column(Boolean, default=False, nullable=False) #用来计算MRR值
    similarity = Column(Float, default=0.0, nullable=False)
    index = Column(Integer, default=0, nullable=False)  # 召回或重排索引
    hit_score = Column(Float, default=0.0, nullable=False)
    all_hit = Column(Boolean, default=False, nullable=False) #用来计算Recall@k值和问题命中数

    create_time = Column(DateTime, nullable=True)


class EvaluationResult(Base):
    """
    评测结果记录表：保存每次评测的汇总指标（如 Recall@k、MRR、命中数等）。
    """
    __tablename__ = TableConfig.EVALUATION_RESULT

    evaluation_result_id = Column(String(64), primary_key=True, index=True, nullable=False)
    evaluation_id = Column(String(64), index=True, nullable=False)
    search_type = Column(String(64), default="semantic", nullable=False)

    recall_k = Column(Float, default=0.0, nullable=False)
    mrr = Column(Float, default=0.0, nullable=False)
    hit_num = Column(Integer, default=0, nullable=False)
    not_hit_num = Column(Integer, default=0, nullable=False)
    evaluation_result_url = Column(String(255), nullable=True)

    update_time = Column(DateTime, nullable=True)
    create_time = Column(DateTime, nullable=True)