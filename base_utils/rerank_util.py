
import json
from loguru import logger
import os
import traceback
from typing import Optional

import requests
from bson import ObjectId
from dotenv import load_dotenv

from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
# logger = loguru logger (auto-migrated)
class RerankUtil:
    """
    rerank工具类
    """

    def __init__(self, rerank_id):
        """
        初始化rerank
        """
        result = MongodbUtil.query_doc_by_id(
            collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(rerank_id)
        )
        logger.info("知识库重排模型查询成功！")
        try:
            if result["is_external"] == True:
                self.rerank_url = f"{result['api_url']}/rerank"
                # self.rerank_url = result["api_url"]
                self.api_key = result["api_key"]
            else:
                self.rerank_url = ModelConfig.RERANK_API_BASE
                self.api_key = ModelConfig.RERANK_API_KEY
        except:
            raise Exception("知识库重排模型id不存在")

    def rerank(
        self,
        model_uid: str,
        documents: list[str],
        query: str,
        top_n: Optional[int],
        return_documents: True = Optional[bool],
    ):
        """
        使用模型对文档进行重新排序并获取分数。

        该函数的主要作用是根据给定的查询字符串和一系列文档，利用已有的模型对文档进行重新排序，
        并返回每个文档与查询的相关性分数。可以选择是否在结果中返回文档的内容。

        参数:
        - documents: List[str] 输入的文档列表，每个文档是一个字符串。
        - query: str 用户的查询字符串。
        - return_documents: bool 是否返回文档内容的标志，默认为True。

        返回:
        - rerank_score_results: 一个包含重新排序后的文档及其相关性分数的结果字典。
        """
        try:
            request_body = {
                "model": model_uid,
                "documents": documents,
                "query": query,
                "top_n": top_n,
                "return_documents": return_documents,
            }

            response = requests.post(self.rerank_url, json=request_body, headers={})
            if response.status_code != 200:
                raise RuntimeError(f"Failed to rerank documents, detail: {response.json()['detail']}")
            response_data = json.loads(response.text)["results"]
            return response_data
        except (Exception, RuntimeError) as e:
            logger.error("异常: %s", traceback.format_exc())

    def socre_rerank(
        self,
        model_uid: str,
        documents: list[str],
        query: str,
        top_n: Optional[int],
        return_documents: True = Optional[bool],
        threshold: Optional[float] = 0.0,
    ):
        """
        使用模型对文档进行重新排序并获取分数。

        该函数的主要作用是根据给定的查询字符串和一系列文档，利用已有的模型对文档进行重新排序，
        并返回每个文档与查询的相关性分数。可以选择是否在结果中返回文档的内容。

        参数:
        - documents: List[str] 输入的文档列表，每个文档是一个字符串。
        - query: str 用户的查询字符串。
        - return_documents: bool 是否返回文档内容的标志，默认为True。

        返回:
        - rerank_score_results: 一个包含重新排序后的文档及其相关性分数的结果字典。
        """
        base_dir = os.path.abspath(os.path.dirname(__file__))
        dotenv_path = os.path.join(os.path.dirname(base_dir), ".production.env")
        load_dotenv(dotenv_path=dotenv_path)
        RERANK_SOURCE = os.getenv("RERANK_SOURCE")
        if RERANK_SOURCE == "tgi":
            try:
                request_body = {
                    "model": model_uid,
                    "texts": documents,
                    "query": query,
                    "top_n": top_n,
                    "return_documents": return_documents,
                }

                if hasattr(self, "api_key"):
                    response = requests.post(
                        self.rerank_url, json=request_body,
                        headers={'Content-Type': 'application/json', "Authorization": f"Bearer {self.api_key}"}
                    )  # 或者 "API-Key": api_key，具体取决于API要求
                else:
                    response = requests.post(
                        self.rerank_url, json=request_body,
                        headers={'Content-Type': 'application/json'}
                    )  # 或者 "API-Key": api_key，具体取决于API要求
                if response.status_code != 200:
                    raise RuntimeError(f"Failed to rerank documents, detail: {response.json()}")

                response_data = response.json()[:top_n]
                for item in response_data:
                    idx = item["index"]

                    item["relevance_score"] = item["score"]
                    item["document"] = {"text": documents[idx]}
                # LogUtil.log_json(describe=":", info=str(response_data))
                if threshold > 0:
                    response_data = [doc for doc in response_data if doc["relevance_score"] >= threshold]
                return response_data
            except (Exception, RuntimeError) as e:
                logger.error("异常: %s", traceback.format_exc())
        else:
            try:
                request_body = {
                    "model": model_uid,
                    "documents": documents,
                    "query": query,
                    "top_n": top_n,
                    "return_documents": return_documents,
                }

                if hasattr(self, "api_key"):
                    response = requests.post(
                        self.rerank_url, json=request_body,
                        headers={'Content-Type': 'application/json', "Authorization": f"Bearer {self.api_key}"}
                    )  # 或者 "API-Key": api_key，具体取决于API要求
                else:
                    response = requests.post(
                        self.rerank_url, json=request_body,
                        headers={'Content-Type': 'application/json'}
                    )  # 或者 "API-Key": api_key，具体取决于API要求
                if response.status_code != 200:
                    raise RuntimeError(f"Failed to rerank documents, detail: {response.json()['detail']}")
                response_data = json.loads(response.text)["results"]
                if threshold > 0:
                    response_data = [doc for doc in response_data if doc["relevance_score"] >= threshold]
                return response_data
            except (Exception, RuntimeError) as e:
                logger.error("异常: %s", traceback.format_exc())


if __name__ == "__main__":
    model_uid = ("bge-reranker-large",)
    query = ("中国的主要节日有哪些？",)
    sentences = [
        "中国的主要节日包括春节、清明节、端午节和中秋节。春节是中国最重要的传统节日，家家户户都会庆祝。",
        "春节通常在农历正月初一庆祝，是中国人团聚和庆祝新年的重要时刻。人们会吃饺子、放鞭炮，并进行各种传统活动。",
        "中秋节是中国的传统节日，通常在农历八月十五庆祝。人们会吃月饼，赏月，庆祝丰收和家庭团聚。",
        "清明节是中国的传统节日之一，主要用于扫墓和祭祖。它通常在公历4月4日至6日之间庆祝。",
        "端午节是为了纪念屈原的节日，人们通常在这一天吃粽子、赛龙舟。",
    ]
    top_n = 3
    rerankUtil = RerankUtil()
    rerankUtil.rerank(model_uid=model_uid, query=query, documents=sentences, top_n=top_n)
