
import openai
from typing import Union
from typing import List, Dict, Any, Optional
import uuid
from openai import OpenAI
from pymilvus import MilvusClient

from base_configs.api_config import ApiConfig

EMBEDDING_URL_FROM_XINFER = ApiConfig.SUPERVISOR_ENDPOINT + "/v1"  # FOR TEMPORARY TEST
DEFAULT_EMBEDDING_MODEL = "bge-base-zh-v1.5"  # FOR TEMPORARY TEST
MILVUS_LITE_URI = "./milvus_demo.db"  # FOR TEMPORARY TEST
DEFAULT_COLLECTION_NAME = "my_milvus"  # FOR TEMPORARY TEST


class OpenAIEmbeddingMilvusService(MilvusClient):
    def __init__(
        self,
        model_uid: str = "",
        collection_name: str = DEFAULT_COLLECTION_NAME,
        uri: str = MILVUS_LITE_URI,
        text_field: str = "text",
        vector_field: str = "vector",
        id_field: str = "id",
        uid_field: str = "doc_uid",
    ):
        super().__init__(uri=uri)
        self.embedding_fn = self.init_embedding_fn()
        self.collection_name = collection_name

        self.model_uid = model_uid
        self.text_field = text_field
        self.vector_field = vector_field
        self.id_field = id_field
        self.docuid_field = uid_field
        if not self.has_collection(self.collection_name):
            self.create_collection(
                collection_name=self.collection_name,
                dimension=768,
                metric_type="IP",  # Inner product distance
                consistency_level="Strong",  # Strong consistency level
            )

    def init_embedding_fn(self):
        return OpenAI(
            api_key="not empty", base_url=EMBEDDING_URL_FROM_XINFER
        ).embeddings

    def get_embedding(self, input: Union[List[str], str]) -> List[float]:
        if input.isinstance(List):
            # 嵌入文本list
            embed_results = self.embedding_fn.create(
                input=input, model=self.model_uid
            ).data
            embeddings = []
            for item in embed_results:
                embeddings.append(item.embedding)
            return embeddings
        else:
            embedding = (
                self.embedding_fn.create(input=input, model=self.model_uid)
                .data[0]
                .embedding
            )
            return embedding

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
        ids: Optional[List[str]] = None,
    ):
        # 嵌入文本
        embeddings = self.get_embeddings(input=texts)

        # 准备插入数据
        entities = []
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in texts]

        for i, (docuid, text, embedding) in enumerate(zip(ids, texts, embeddings)):
            entity = {
                self.id_field: i,
                self.docuid_field: docuid,
                self.text_field: text,
                self.vector_field: embedding,
            }
            if metadatas:
                entity.update(metadatas[i])
            entities.append(entity)

        # 插入数据
        self.insert(collection_name=self.collection_name, data=entities)
        return ids

    def parse_results(self, results):
        result_dict = {}
        for i, item in enumerate(results):
            result_dict[f"No_{i}"] = item
        return result_dict

    def similarity_search_with_score(self, query: str, limit: int = 4):
        # 执行相似性搜索并返回得分
        query_embedding = (
            self.embedding_fn.create(input=query, model=self.model_uid)
            .data[0]
            .embedding
        )

        search_params = {"metric_type": "IP"}
        results = self.search(
            collection_name=self.collection_name,
            data=[query_embedding],
            anns_field=self.vector_field,
            search_params=search_params,
            limit=limit,
            output_fields=[
                self.text_field,
            ],
        )

        return self.parse_results(results=results[0])


class OpenAIEmbeddingService:
    def __init__(
        self,
        model_uid: str = DEFAULT_EMBEDDING_MODEL,
        embedding_url: str = EMBEDDING_URL_FROM_XINFER,
    ):
        self.model_uid = model_uid
        self.embedding_url = embedding_url
        self.client = openai.Client(api_key="not empty", base_url=self.embedding_url)

    def get_embedding(self, sentences: Union[str, list]) -> list:
        """
        获取向量
        :param sentences: 句子列表
        :return: 向量列表
        """
        embedding_results = self.client.embeddings.create(
            input=sentences,
            model=self.model_uid,
        )

        embeddings = []

        for item in embedding_results.data:
            embeddings.append(item.embedding)

        return embeddings


if __name__ == "__main__":
    from langchain_community.document_loaders import PDFPlumberLoader

    loader = PDFPlumberLoader(".\防震知识问答.pdf")

    docs = loader.load_and_split()

    docs_content = []

    for item in docs:
        docs_content.append(item.page_content)

    # 创建 CustomMilvusWithEmbedding 实例
    custom_milvus = OpenAIEmbeddingMilvusService(
        model_uid=DEFAULT_EMBEDDING_MODEL,  # 可选，如果不指定将使用 DEFAULT_EMBEDDING_MODEL
        collection_name="my_milvus",  # 可选，这是默认值
        uri=".\milvus_demo.db",  # 可选，指定一个不同的数据库路径
        text_field="text",  # 可选，如果你想使用不同的字段名
        vector_field="vector",  # 可选，如果你想使用不同的字段名
        id_field="id",  # 可选，如果你想使用不同的 ID 字段名
        uid_field="doc_uid",
    )
