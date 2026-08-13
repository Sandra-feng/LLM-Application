
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class AgentInfo(BaseModel):
    agent_name: str = Field(..., examples=["finaicialRAG"], description="智能体名称")
    description: str = Field(..., examples=["用于RAG检索"], description="智能体描述")
    team_code: Optional[str] = Field(None, description="团队code列表", examples=["1"])
    item_type: str = Field(..., examples=["子类别"], description="智能体子类别")
    type_name: str = Field(..., examples=["子类别"], description="智能体子类别名称")


class AgentTeamInfo(BaseModel):
    agent_name: str = Field(..., examples=["finaicialRAG"], description="智能体名称")
    description: str = Field(..., examples=["用于RAG检索"], description="智能体描述")
    team_code: str = Field(..., examples=["test2"], description="团队code")


class ArrangeAgentInfo(BaseModel):
    agent_id: str = Field(..., examples=["678a0372887170f57a2f976f"], description="智能体id")
    model_params: dict = Field(
        ...,
        examples=[{"model_uid": "qwen2-72B", "max_token_length": 5096, "temperature": 0.8, "history": 3}],
        description="模型uid",
    )
    prompt_id: str = Field("", examples=["PROMPT_123"], description="提示词id")
    prompt: str = Field(..., examples=["你是一个数据分析专家"], description="智能体提示词")
    promptHtml: str = Field("", examples=["html"], description="智能体提示词html版")
    recall_setting: dict = Field(
        ..., examples=[{"rerank_model": "bge-reranker-large", "top_k": 5, "score": 0.2}], description="召回设置"
    )
    kb_list: list = Field(
        ..., examples=[["6787518dfb8499f13bd3dd52", "678e2729d83327b234b00818"]], description="知识库列表id"
    )
    tool_list: list = Field(
        ...,
        examples=[
            ["system_tools", "1", "tool_id"],
            ["system_tools", "0", "tool_id"],
            ["mcp_tools", "server_id", "tool_name1"],
            ["mcp_tools", "server_id", "tool_name2"],
            ["mcp_tools", "server_id", "tool_name3"],
        ],  # 1代表内置工具，0代表自定义工具
        description="工具集id列表!",
    )
    variable_list: list = Field([], examples=[["a", "b"]], description="变量列表")
    is_question_rewriting: bool = Field(False, description="是否问题改写")


class QueryAgentInfo(BaseModel):
    agent_name: str = Field(..., examples=["fin"], description="智能体模糊查询名称")
    page: int = Field(..., examples=[1], description="页码")
    page_size: int = Field(..., examples=[2], description="页面大小")
    status: Optional[int] = Field(None, description="状态：0-未发布，1-已发布")
    team_codes: Optional[list] = Field(None, description="团队code列表", examples=[["1", "10001"]])
    item_type: str = Field(..., examples=["agent-type"], description="子类别code")


class QueryAgentInfo1(BaseModel):
    agent_name: str = Field(..., examples=["fin"], description="智能体模糊查询名称")
    page: int = Field(..., examples=[1], description="页码")
    page_size: int = Field(..., examples=[2], description="页面大小")
    status: Optional[int] = Field(None, description="状态：0-未发布，1-已发布")
    team_codes: Optional[list] = Field(None, description="团队code列表", examples=[["1", "10001"]])
    item_type: str = Field(..., examples=["agent-type"], description="子类别code")
    id: Optional[str] = Field("", examples=["agent-type"], description="子类别code")


class QueryTeamAgentInfo(BaseModel):
    agent_name: str = Field(..., examples=[""], description="智能体模糊查询名称")
    page: int = Field(..., examples=[1], description="页码")
    page_size: int = Field(..., examples=[10], description="页面大小")
    status: Optional[int] = Field(None, description="状态：0-未发布，1-已发布")
    team_code: list = Field([], examples=[["1", "10001"]], description="团队code列表")
    id: str = Field(..., examples=["agent-type"], description="子类别code")


class TestAgentInfo(BaseModel):
    agent_id: str = Field(..., examples=["6735529d012d26f6f9b9c742"], description="智能体id")
    input: str = Field(..., examples=["未满十四周岁的未成年信息保护"], description="对话输入")
    conversation_id: str = Field("", description="会话ID")
    agent_params: dict = Field({}, description="智能体参数")
    system_prompts: str = Field("", description="系统角色提示语")
    prompt_id: str = Field("", description="提示词id")


class TestAgentInfo_v2(BaseModel):
    agent_id: str = Field(..., examples=["6735529d012d26f6f9b9c742"], description="智能体id")
    agent_input: str = Field(..., examples=["未满十四周岁的未成年信息保护"], description="对话输入")
    agent_params: dict = Field({}, description="智能体参数")
    conversation_id: str = Field("", description="智能体参数")
    system_prompts: str = Field("", description="系统角色提示语")
    prompt_id: str = Field("", description="提示词id")
    need_new_source: bool = Field(True, description="是否需要返回检索切片来源信息，默认需要")


class TestAgentInfo_v1(BaseModel):
    account_id: str = Field("", examples=["6735529d012d26f6f9b9c742"], description="account_id")
    agent_id: str = Field(..., examples=["6735529d012d26f6f9b9c742"], description="智能体id")
    input: str = Field(..., examples=["未满十四周岁的未成年信息保护"], description="对话输入")
    conversation_id: str = Field("", description="会话ID")
    agent_params: dict = Field({}, description="智能体参数")
    system_prompts: str = Field("", description="系统角色提示语")
    prompt_id: str = Field("", description="提示词id")
    need_new_source: bool = Field(True, description="是否需要返回检索切片来源信息")


class TypeDict(BaseModel):
    code: str = Field(..., examples=["agent-type"], description="编码")
    name: str = Field(..., examples=["语言模型"], description="中文名称")
    description: str = Field(..., examples=["这是一个语言模型类别"], description="描述")


class TypeUpdateDict(BaseModel):
    id: str = Field(..., examples=["681affff8fbe31c31dd76365"], description="主键id")
    code: str = Field(..., examples=["model-type2"], description="编码")
    name: str = Field(..., examples=["语言模型2"], description="中文名称")
    description: str = Field(..., examples=["这是一个语言模型类别2"], description="描述")
    # cn_spell: str = Field("", example="", description="拼音缩写")
    # scope_type: str = Field("", example="", description="范围类型")
    status: str = Field(..., examples=["1"], description="状态")


class TypeItemDict(BaseModel):
    code: str = Field(..., examples=["LLM-agent"], description="编码")
    type_code: str = Field(..., examples=["agent-type"], description="子类别")
    name: str = Field(..., examples=["语言模型"], description="中文名称")
    description: str = Field(..., examples=["这是一个语言模型类别"], description="描述")


class TypeItemUpdateDict(BaseModel):
    id: str = Field(..., examples=["681affff8fbe31c31dd76365"], description="主键id")
    code: str = Field(..., examples=["model-type2"], description="编码")
    type_code: str = Field(..., examples=["model-type2"], description="编码")
    name: str = Field(..., examples=["语言模型2"], description="中文名称")
    description: str = Field(..., examples=["这是一个语言模型类别2"], description="描述")
    status: str = Field(..., examples=["1"], description="状态")


class TypeItemDelete(BaseModel):
    id: str = Field(..., examples=["681affff8fbe31c31dd76365"], description="主键id")


class TypeDelete(BaseModel):
    id: str = Field(..., examples=["681affff8fbe31c31dd76365"], description="主键id")
