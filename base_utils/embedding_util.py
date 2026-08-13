# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：bge_util.py
@Author  ：JianbinLi
@Date    ：2024/09/13 17:57
"""

from typing import Union

import openai
from bson import ObjectId
from loguru import logger

from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil


# logger = loguru logger (auto-migrated)
class EmbeddingUtil:
    """
    embedding工具类
    """

    def __init__(self, embedding_id):
        """
        初始化embedding
        """
        MongodbUtil.connect()
        result = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(embedding_id)
        )

        if result["is_external"] == True:
            # 替换为 logger，避免直接记录敏感信息（如 api_key）
            logger.info("API Key 已配置（长度: %d）", len(result["api_key"]))
            self.embedding_client = openai.Client(api_key=result["api_key"], base_url=result["api_url"])
        else:
            self.embedding_client = openai.Client(
                api_key=ModelConfig.EMBED_API_KEY, base_url=ModelConfig.EMBED_API_BASE
            )

    def get_embedding(
        self, model_uid: str, input: Union[str, list], return_sparse: bool = False, silent_on_error: bool = False
    ):
        """
        获取向量
        :model_uid: 模型UID
        :param input: 句子
        :param return_sparse: 是否返回稀疏向量
        :param silent_on_error: 出错时是否静默（不记录异常日志）
        :return: 向量列表
        """
        try:
            embedding_results = self.embedding_client.embeddings.create(
                input=input,
                model=model_uid,
                extra_body={
                    "return_sparse": return_sparse,
                },
            )

            embeddings = []

            for item in embedding_results.data:
                embeddings.append(item.embedding)

            return embeddings
        except (Exception, RuntimeError) as e:
            if not silent_on_error:
                logger.exception("生成向量异常", str(e))
            raise


if __name__ == "__main__":
    embedding_client = EmbeddingUtil()
    res = embedding_client.get_embedding(model_uid="bge-base-zh-v1.5", input="今天天气如何")
    if res:
        print(type(res))
        print("嵌入成功！")
    else:
        print("出错")
    print(res)
