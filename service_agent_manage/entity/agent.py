from typing import Optional

from pydantic import BaseModel, Field


class CallAgentParams(BaseModel):
    agent_id: str = Field(..., examples=["6735529d012d26f6f9b9c742"], description="智能体id")
    input: str = Field(..., examples=["未满十四周岁的未成年信息保护"], description="对话输入")
    conversation_id: str = Field("", description="会话ID")
    agent_params: Optional[dict] = Field(None, description="智能体参数，用于prompt参数替换")
