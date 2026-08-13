#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File         :launch_entity.py
@Description  :
@Author       :QiangQu
@Date         :2024/08/28 18:26:08
'''

from pydantic import BaseModel, Field
from typing import Optional, Union

class LLMModelInfo(BaseModel):
    model_id: str = Field(..., examples=["qwen1.5-chat"], description="模型ID")
    model_uid: str = Field(..., examples=["qwen1.5-7B-chat"], description="模型UID")
    model_engine: str = Field(..., examples=["vLLM"], description="模型引擎")
    model_size_in_billions: Union[int, str] = Field(..., examples=[7], description="模型大小")
    model_format: str = Field(..., examples=["pytorch"], description="模型格式")
    quantization: str = Field(..., examples=["none"], description="模型量化")
    model_type: str = Field(..., examples=["LLM"], description="模型类型")
    replica: int = Field(..., examples=[1], description="模型副本数")
    device: str = Field(..., examples=["GPU"], description="运行设备, 值为GPU或CPU")
    request_limits: Optional[int] = Field(None, examples=[None], description="请求限制数")
    lora_list: Optional[list[dict]] = Field(None, examples=[None], description="lora模型列表")
    worker_ip: Optional[str] = Field(None, examples=[None], description="节点ip")
    gpu_idx: Optional[list] = Field([0], examples=[[0]], description="gpu下标")
    download_hub: str = Field("modelscope", examples=["modelscope"], description="下载平台")
    model_path: Optional[str] = Field(..., examples=[None], description="模型路径")
    model_engine_params: dict = Field({}, examples=[{}], description="模型引擎参数")
    is_think: Optional[bool] = Field(None, examples=[True], description="是否为推理模型")
    modalities: Optional[list] = Field([], examples=[[]], description="模型支持类型列表")
    is_realtime: Optional[bool] = Field(None, examples=[True], description="语音模型是否支持实时")

class CommonModelInfo(BaseModel):
    model_id: str = Field(..., examples=["bge-base-zh-v1.5"], description="模型ID")
    model_uid: str = Field(..., examples=["bge-base-zh-v1.5"], description="模型UID")
    model_type: str = Field(..., examples=["embedding"], description="模型类型")
    replica: int = Field(..., examples=[1], description="模型副本数")
    device: str = Field("GPU", examples=["GPU"], description="运行设备, 值为GPU或CPU")
    worker_ip: Optional[str] = Field(None, examples=[None], description="节点ip")
    gpu_idx: Optional[list] = Field([0], examples=[[0]], description="gpu下标")
    download_hub: str = Field("modelscope", examples=["modelscope"], description="下载平台")
    model_path: Optional[str] = Field(None, examples=[None], description="模型路径")
    mode: Optional[str] = Field("", examples=[""], description="语音模型类型")
    is_realtime: Optional[bool] = Field(None, examples=[True], description="语音模型是否支持实时")

class AccessModelInfo(BaseModel):
    model_name: str = Field(..., examples=["qwen2.5-72B"], description="模型别称")
    model_uid: str = Field(..., examples=["qwen2.5-72B"], description="模型UID")
    model_type: str = Field(..., examples=["LLM"], description="模型类型")
    api_url: str = Field(..., examples=["http://10.8.21.164:9997/v1"], description="api地址")
    api_key: str = Field(..., examples=["not empty"], description="api密钥")
    max_model_len: Optional[int] = Field(None, examples=[4096], description="模型最大上下文长度")
    max_tokens: Optional[int] = Field(None, examples=[4096], description="模型的最大输出长度")
    is_think: Optional[bool] = Field(None, examples=[True], description="是否为推理模型")
    is_vision: Optional[bool] = Field(None, examples=[True], description="是否为图生文模型")
    modalities: Optional[list] = Field([], examples=[[]], description="模型支持类型列表")
    is_realtime: Optional[bool] = Field(None, examples=[True], description="语音模型是否支持实时")
    mode: Optional[str] = Field("", examples=[""], description="语音模型类型")

class AccessModel_updateInfo(BaseModel):
    id: str = Field(..., examples=[""], description="工作流id")
    model_name: str = Field(..., examples=["qwen2.5-72B"], description="模型别称")
    model_uid: str = Field(..., examples=["qwen2.5-72B"], description="模型UID")
    model_type: str = Field(..., examples=["LLM"], description="模型类型")
    api_url: str = Field(..., examples=["http://10.8.21.164:9997/v1"], description="api地址")
    api_key: str = Field(..., examples=["not empty"], description="api密钥")
    max_model_len: Optional[int] = Field(None, examples=[4096], description="模型最大上下文长度")
    max_tokens: Optional[int] = Field(None, examples=[4096], description="模型的最大输出长度")
    is_think: Optional[bool] = Field(None, examples=[True], description="是否为推理模型")
    is_vision: Optional[bool] = Field(None, examples=[True], description="是否为图生文模型")
    is_realtime: Optional[bool] = Field(None, examples=[True], description="语音模型是否支持实时")
    mode: Optional[str] = Field("", examples=[""], description="语音模型类型")
