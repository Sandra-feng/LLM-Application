

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class CreateAgentRequest(BaseModel):
    """创建智能体请求"""

    agent_name: str = Field(..., examples=["财务分析助手"], description="智能体名称")
    description: Optional[str] = Field(None, examples=["专业的财务数据分析智能体"], description="智能体描述")
    team_code: Optional[str] = Field(None, examples=["TEAM001"], description="团队代码")
    item_type: Optional[str] = Field(None, examples=["1"], description="智能体类型")
    type_name: Optional[str] = Field(None, examples=["财务类型"], description="类型名称")


class UpdateAgentRequest(BaseModel):
    """更新智能体请求"""

    agent_id: str = Field(..., examples=["6735529d012d26f6f9b9c742"], description="智能体id")
    agent_name: str = Field(None, examples=["财务分析助手"], description="智能体名称")
    description: Optional[str] = Field(None, examples=["专业的财务数据分析智能体"], description="智能体描述")
    team_code: Optional[str] = Field(None, examples=["TEAM001"], description="团队代码")
    item_type: Optional[str] = Field(None, examples=["finance"], description="智能体类型")


class AgentResponse(BaseModel):
    """智能体响应对象"""

    id: str = Field(..., description="智能体ID")
    agent_name: str = Field(..., description="智能体名称")
    description: str = Field(..., description="智能体描述")
    team_code: Optional[str] = Field(None, description="团队代码")
    item_type: str = Field(..., description="智能体类型")
    type_name: str = Field(..., description="类型名称")
    status: int = Field(..., description="状态：0-未发布，1-已发布")
    created_at: datetime = Field(..., description="创建时间")
    created_by: str = Field(..., description="创建人")


class AgentListRequest(BaseModel):
    """智能体列表查询请求"""

    agent_keyword: Optional[str] = Field(None, description="智能体名称模糊查询")
    team_code: Optional[list] = Field(None, description="团队代码")
    item_type: Optional[str] = Field(None, description="智能体类型")
    status: Optional[int] = Field(None, description="状态：0-未发布，1-已发布")
    page: int = Field(1, ge=1, description="页码")
    page_size: int = Field(10, ge=1, le=100, description="每页数量")
    id: Optional[str] = Field("", description="类型名称")


class AgentListResponse(BaseModel):
    """智能体列表响应"""

    total: int = Field(..., description="总数")
    page: int = Field(..., description="当前页码")
    page_size: int = Field(..., description="每页数量")
    items: list[AgentResponse] = Field(..., description="智能体列表")


class ApiResponse(BaseModel):
    """统一API响应格式"""

    status: bool = Field(..., description="请求状态")
    message: str = Field(..., description="响应消息")
    data: Optional[Any] = Field(None, description="响应数据")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间")
