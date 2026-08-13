# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：model_config.py
@Author  ：JianbinLi
@Date    ：2024/09/13 15:42
"""

from base_configs.api_config import ApiConfig


class ModelConfig(object):
    """
    模型配置
    """
    NORMAL_LLM = "qwen2.5-72B"
    # 大语言模型配置
    LLM_API_KEY = "not empty"
    LLM_API_BASE = ApiConfig.SUPERVISOR_ENDPOINT + "/v1"  # Openai API

    # 向量模型配置
    EMBED_API_KEY = "not empty"
    EMBED_API_BASE = ApiConfig.SUPERVISOR_ENDPOINT + "/v1"  # Openai API
    DEFAULT_EMBEDDING_MODEL = "bge-large-zh-v1.5"

    # 重排模型配置
    RERANK_API_KEY = "not empty"
    RERANK_API_BASE = ApiConfig.SUPERVISOR_ENDPOINT + "/v1/rerank"  # restful API
    DEFAULT_RERANK_MODEL = "bge-reranker-large"

    # 语音模型配置
    AUDIO_API_KEY = "not empty"
    AUDIO_API_BASE = ApiConfig.SUPERVISOR_ENDPOINT + "/v1"

    # 重排模型配置
    IMAGE_API_KEY = "not empty"
    IMAGE_API_BASE = ApiConfig.SUPERVISOR_ENDPOINT + "/v1"  # restful API
    DEFAULT_IMAGE_URL = "http://10.8.21.164:9997"