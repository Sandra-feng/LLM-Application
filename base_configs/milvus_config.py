#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：milvus_config.py
@Author  ：TaoMeng
@Date    ：2024/8/25 22:39
"""

from base_configs.api_config import ApiConfig


class MilvusConfig:
    """
    milvus配置
    """

    # Milvus连接信息
    MILVUS_CONNECT_INFO = {
        "uri": "http://{}".format("10.8.21.165:19530"),
        "user": "",
        "password": "",
        "secure": False,
        "db_name": "tiance_base",  # 测试用RAG_TEST，正式用qi_wen_kb,1.3.1迁移为tiance_base
    }

    # Milvus默认输出fields
    DEFAULT_MILVUS_OUTPUT_FIELDS = [
        "content",
        "file_id",
        "number",
        "file_name",
        "file_time",
        "source_data",
        # 新增：父子切块相关字段
        "chunk_split_type",
        "chunk_id",
        "parent_node",
    ]

    # 混合检索相关配置
    HYBRID_SEARCH_CONFIG = {
        "enable_bm25": True,  # 是否启用BM25全文检索
        "enable_model_sparse": False,  # 是否启用模型稀疏向量(如bge-m3)
        "default_search_limit": 512,  # 每个向量字段的默认搜索数量
        "fusion_method": "rrf",  # 融合方法: "rrf" 或 "weighted"
        "rrf_k": 60,  # RRF参数
        "weights": [0.7, 0.3],  # 加权融合权重 [dense, sparse]
    }

    # 索引配置
    INDEX_CONFIG = {
        "dense": {
            "index_type": ApiConfig.index_type,  # GPU_IVF_FLAT，GPU_IVF_PQ,具体用法查看https://milvus.io/docs/
            "metric_type": "COSINE",  # 或 "IP", "L2"
        },
        "sparse_bm25": {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "BM25",
            "params": {
                "inverted_index_algo": "DAAT_MAXSCORE",
                "bm25_k1": 1.2,
                "bm25_b": 0.75,
            },
        },
        "sparse_model": {
            "index_type": "SPARSE_INVERTED_INDEX",
            "metric_type": "IP",
            "params": {
                "inverted_index_algo": "DAAT_MAXSCORE",
                "drop_ratio_build": 0.2,
                "drop_ratio_search": 0.3,
            },
        },
    }
