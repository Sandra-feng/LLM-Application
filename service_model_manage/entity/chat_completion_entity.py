# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：chat_completion_entity.py
@Author  ：JianbinLi
@Date    ：2024/08/29 13:54
"""

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from service_knowledge_manage.entity.knowledge_hub_entity import KnowledgeRetrivalInfo


class ChatCompletionRequestParams_r1(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    该模型定义了与对话交互相关的请求所需的字段，包括模型的唯一标识符、
    系统角色提示信息、用户问题、对话历史轮数、模型最大生成长度以及温度参数。
    """

    system_prompts: str = Field("You are a helpful assistant,", description="系统角色提示语")
    question: str = Field("你好", description="用户问题")
    max_token_length: Optional[int] = Field(4096, description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, description="温度参数")


class ChatCompletionRequestParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    该模型定义了与对话交互相关的请求所需的字段，包括模型的唯一标识符、
    系统角色提示信息、用户问题、对话历史轮数、模型最大生成长度以及温度参数。
    """

    model_uid: str = Field("glm4-chat", description="模型UID")
    system_prompts: str = Field("You are a helpful assistant,", description="系统角色提示语")
    chatbot: list[dict] = Field([], description="对话记录")
    question: str = Field("你好", description="用户问题")
    history: Optional[int] = Field(3, description="对话历史轮数")
    max_token_length: Optional[int] = Field(4096, description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, description="温度参数")


class vl_ChatCompletionRequestParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    该模型定义了与对话交互相关的请求所需的字段，包括模型的唯一标识符、
    系统角色提示信息、用户问题、对话历史轮数、模型最大生成长度以及温度参数。
    """

    model_uid: str = Field("glm4-chat", description="模型UID")
    images: list[str] = Field([], description="图片地址")
    system_prompts: str = Field("You are a helpful assistant,", description="系统角色提示语")
    question: str = Field("你好", description="用户问题")
    max_token_length: Optional[int] = Field(4096, description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, description="温度参数")


class ChatCompletionRequestParams_v1(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    该模型定义了与对话交互相关的请求所需的字段，包括模型的唯一标识符、
    系统角色提示信息、用户问题、对话历史轮数、模型最大生成长度以及温度参数。
    """

    knowledge_id: str = Field("", description="知识库id")
    id: str = Field("", description="模型数据库的唯一标识")
    model_uid: str = Field("glm4-chat", description="模型UID")
    system_prompts: str = Field("You are a helpful assistant,", description="系统角色提示语")
    history: Optional[int] = Field(3, description="对话历史轮数")
    max_token_length: Optional[int] = Field(4096, description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, description="温度参数")
    conversation_id: str = Field("", description="会话ID")
    talk_id: str = Field("", description="对话ID，非必填")
    tool_label: int = Field(0, description="是否启用工具")
    retrival_params: KnowledgeRetrivalInfo = Field({}, description="知识库检索参数")
    presence_penalty: Optional[float] = Field(0, description="存在惩罚")
    frequency_penalty: Optional[float] = Field(0, description="频率惩罚")
    type: Optional[int] = Field(5, description="对话类型，默认为5")
    is_question_rewriting: Optional[bool] = Field(default=False, description="是否问题改写")
    synonym: Optional[list] = Field([], description="同义词组")

    model_config = ConfigDict(
        extra="allow",  # 允许额外字段
        validate_by_name=True,  # 替代 allow_population_by_field_name
    )


class ChatCompletionHistoryParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    """

    history: Optional[int] = Field(3, description="对话历史轮数")
    conversation_id: str = Field("", description="会话ID")


class ChatCompletionListParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    """

    type: Optional[int] = Field(4, description="对话类型")
    model_id: str = Field("", description="模型ID")
    kb_id: str = Field("", description="知识库ID")
    ag_id: str = Field("", description="智能体ID")


class ChatCompletionListParams_mem(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    """

    type: Optional[int] = Field(4, description="对话类型")
    model_id: str = Field("", description="模型ID")
    kb_id: str = Field("", description="知识库ID")
    ag_id: str = Field("", description="智能体ID")
    creat: str = Field("", description="是否新增")


class ChatCompletionRequestParams_r1(BaseModel):
    system_prompts: str = Field("You are a helpful assistant,", description="系统角色提示语")
    question: str = Field("你好", description="用户问题")
    max_token_length: Optional[int] = Field(4096, description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, description="温度参数")


class multi_model_ChatCompletionRequestParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    该模型定义了与对话交互相关的请求所需的字段，包括模型的唯一标识符、
    系统角色提示信息、用户问题、对话历史轮数、模型最大生成长度以及温度参数。
    """

    id: str = Field("", description="模型数据库的唯一标识")
    model_uid: str = Field("glm4-chat", description="模型UID")
    system_prompts: str = Field("You are a helpful assistant,", description="系统角色提示语")
    history: Optional[int] = Field(3, description="对话历史轮数")
    max_token_length: Optional[int] = Field(4096, description="模型最大生成长度")
    temperature: Optional[float] = Field(0.8, description="温度参数")
    presence_penalty: Optional[float] = Field(0, description="存在惩罚")
    frequency_penalty: Optional[float] = Field(0, description="频率惩罚")
    conversation_id: str = Field("", description="会话ID")
    talk_id: str = Field("", description="对话ID，非必填")
    images: list[str] = Field([], description="图片参数，可以是图片的URL或本地路径")
    tool_label: int = Field(0, description="是否启用工具")
    retrival_params: KnowledgeRetrivalInfo = Field({}, description="知识库检索参数")
    type: Optional[int] = Field(5, description="对话类型，默认为5")
    onlineSearch: Optional[bool] = Field(False, description="是否需要进行联网搜索")


class Multimodel_ChatParams(BaseModel):
    """
    cnooc页面对话入参
    """

    model_uid: str = Field("Qwen3_VL_32B", description="模型UID")
    history: Optional[int] = Field(3, description="对话历史轮数")
    conversation_id: str = Field("", description="会话ID")
    images: list[str] = Field([], description="图片参数，可以是图片的URL或本地路径")
    user_query: str = Field("", description="用户提问的问题")
    talk_id: str = Field("", description="对话ID，非必填")
    type: Optional[int] = Field(5, description="对话类型，默认为5")


class ExportChatCompletionHistoryParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    """

    conversation_id: list[str] = Field([], description="会话ID")
    talk_id: list[str] = Field([], description="对话ID")


class ChatLikeReviewParams(BaseModel):
    """
    用于处理对话完成请求的数据模型。

    """

    talk_id: str = Field(..., description="对话ID")
    talk_review: str = Field("", description="反馈内容")
    answer_review_tag: list = Field([], description="回答内容标签")
    talk_num: int = Field(0, description="对话轮数")
