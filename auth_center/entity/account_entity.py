#!/usr/bin/env python
from pydantic import BaseModel, Field


class AccountEntity(BaseModel):
    username: str = Field(..., examples=["A123"], description="账号名称")
    password: str = Field(..., examples=[123], description="密码")


class AccountEntityNew(BaseModel):
    account_name: str = Field(..., examples=["A123"], description="账号名称")
    password: str = Field(..., examples=[123], description="密码")


class ULoginEntity(BaseModel):
    username: str = Field(..., examples=["A123"], description="用户名")
    password: str = Field(..., examples=["123456"], description="明文密码")

class URegisterEntity(BaseModel):
    account_name: str = Field(..., examples=["测试账号"], description="账号名称")
    user_name: str = Field(..., examples=["张三"], description="用户名称")
    password: str = Field(..., examples=["123456"], description="账号密码")