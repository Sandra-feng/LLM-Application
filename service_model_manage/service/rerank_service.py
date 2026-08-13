

from typing import List, Optional
from base_configs.api_config import ApiConfig
import requests

DEFAULT_RERANKER_MODEL = "bge-reranker-large"  # FOR TEMPORARY TEST
RERANK_URL_FROM_XINFER = ApiConfig.SUPERVISOR_ENDPOINT  # FOR TEMPORARY TEST


class XinferRerankService:
    def __init__(
        self,
    ):
        self.rerank_url = f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1/rerank"

    def get_rerank_scores(
        self,
        model_uid: str,
        documents: List[str],
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
        request_body = {
            "model": model_uid,
            "documents": documents,
            "query": query,
            "top_n": top_n,
            "return_documents": return_documents,
        }
        response = requests.post(self.rerank_url, json=request_body, headers={})
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to rerank documents, detail: {response.json()['detail']}"
            )
        response_data = response.json()
        return response_data
