#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File         :model_supervise_entity.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/03 11:51:47
'''

from pydantic import BaseModel, Field
from typing import Union

class ModelRunInfoResponse(BaseModel):
    model_name: str = Field(..., examples=["bge-base-zh-v1.5"], description="模型名")
    model_uid: str = Field(..., examples=["bge-base-zh-v1.5"], description="模型UID")
    address: str = Field(..., examples=["0.0.0.0:42789"], description="模型运行地址")
    gpu_idx: list = Field(..., examples=[["0"]], description="GPU下标")
    model_size_in_billions: Union[int, str] = Field(..., examples=[""], description="模型大小")
    quantizations: str = Field(..., examples=[""], description="模型量化")
    replica: int = Field(..., examples=[1], description="模型副本数")
    status: str = Field(..., examples=["running"], description="模型运行状态 运行=running 停止=stop")
    modify_time: str = Field(..., examples=["2024-09-02 18:04:56"], description="修改时间")