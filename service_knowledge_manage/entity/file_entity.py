#!/usr/bin/env python
"""
@File         :file_entity.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/03 17:33:49
"""

from pydantic import BaseModel, Field


class FileQueryInfo(BaseModel):
    id: str = Field(..., examples=["test_00001"], description="知识库名id")
    file_name: str = Field(..., examples=["test_00001"], description="知识库名")
    page: int = Field(..., examples=[1], description="页码")
    page_size: int = Field(..., examples=[10], description="分页大小")


class ChunkQueryInfo(BaseModel):
    id: str = Field(..., examples=["test_00001"], description="知识库名id")
    file_id: list = Field(..., examples=["F1877671369328693248"], description="知识库名")
    filter_condition: str | None = Field(None, examples=["report"], description="切片内容模糊筛选条件")
    page: int = Field(..., examples=[1], description="页码")
    page_size: int = Field(..., examples=[10], description="分页大小")

class FileInfoResponse(BaseModel):
    file_name: str = Field(..., examples=["test.xlsx"], description="文件名")
    upload_time: str = Field(..., examples=["2024-09-03 17:39:34"], description="上传时间")


class ChunkResultResponse(BaseModel):
    number: int = Field(..., examples=[1], description="序号")
    file_name: str = Field(..., examples=["test.xlsx"], description="文件名")
    chunk_content: str = Field(..., examples=["切片内容"], description="切片内容")


class ChunkEditInfo(BaseModel):
    id: str = Field(..., examples=[1], description="节点id")
    new_content: str = Field(..., examples=["test.xlsx"], description="新内容")
    file_id: str = Field(..., examples=["切片内容"], description="文件id")
