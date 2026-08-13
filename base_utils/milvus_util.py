#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：milvus_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:21
"""
from typing import Optional
from pathlib import Path
import os
from dotenv import load_dotenv
from lazy_object_proxy.utils import await_
from pymilvus.milvus_client import IndexParams
from pymilvus import (
    CollectionSchema,
    AsyncMilvusClient,
    connections,
    Collection,
    MilvusClient,
)
from pprint import pprint
from base_utils.log_util import LogUtil

# from base_configs.milvus_config import MilvusConfig
from base_configs.milvus_config import MilvusConfig


# 通过直接导出类，保持了向后兼容性。
# 执行“from base_utils.milvus_util import MilvusUtil”的代码
# 可以通过‘ MilvusUtil() ’继续实例化它。
# 实现现在是正确的分层和抽象。
# 后续只需导入对应的数据库仓储类，无需修改业务代码
# MilvusUtil 只是一个插座，你可以导入不同的向量数据库实现（比如Milvus、Pinecone、Faiss等）
from data_access.implementations.milvus_repository import MilvusRepository as MilvusUtil
from data_access.implementations.milvus_repository import MilvusConfig

base_dir = Path(__file__).resolve().parent
dotenv_path = os.path.join(base_dir, ".local.env")
if not os.path.exists(dotenv_path):
    dotenv_path = os.path.join(base_dir, ".production.env")
load_dotenv(dotenv_path=dotenv_path)
VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE")
# 后续可以根据环境变量动态选择向量数据库实现
# VECTOR_DB_TYPE = os.getenv("VECTOR_DB_TYPE", "milvus").lower()
if VECTOR_DB_TYPE == "milvus":
    from data_access.implementations.milvus_repository import (
        MilvusRepository as MilvusUtil,
        # MilvusCollectionRepository as MilvusCollectionUtil,
        # MilvusConfig,
    )
elif VECTOR_DB_TYPE == "opengauss":
    from data_access.implementations.opengauss_repository import (
    OpenGaussRepository as MilvusUtil,

    )
# 这里可以扩展支持其他向量数据库实现，例如 Pinecone、Faiss 等
# elif VECTOR_DB_TYPE == "pinecone":
#     from data_access.implementations.pinecone_repository import (
#         PineconeRepository as MilvusUtil,
#         PineconeCollectionRepository as MilvusCollectionUtil,
#         PineconeConfig as MilvusConfig,
#     )
# elif VECTOR_DB_TYPE == "faiss":
#     from data_access.implementations.faiss_repository import (
#         FaissRepository as MilvusUtil,
#         FaissCollectionRepository as MilvusCollectionUtil,
#         FaissConfig as MilvusConfig,
#     )
# else:
#     raise ImportError(f"不支持的向量数据库类型: {VECTOR_DB_TYPE}")




# class MilvusConfig(object):
#     """
#     milvus配置
#     """

#     # 知识库连接信息
#     MILVUS_CONNECT_INFO = MilvusConfig.MILVUS_CONNECT_INFO

#     # Milvus默认输出fields
#     DEFAULT_MILVUS_OUTPUT_FIELDS = [
#         "content",
#         "file_id",
#         "number",
#         "file_name",
#         "file_time",
#         "source_data",
#     ]


# class MilvusCollectionUtil(object):
#     """
#     Collection工具类（非异步）
#     """

#     def __init__(self, alias: str):
#         """
#         连接数据库
#         :param alias: 连接的别名，用于断开连接
#         :return:
#         """
#         # 获取连接配置
#         connection_config = MilvusConfig.MILVUS_CONNECT_INFO
#         if connection_config is None:
#             raise ValueError(f"向量数据库的连接配置未找到")
#         # 获得连接对象
#         connections.connect(alias=alias, **connection_config)
#         # connections.connect(alias=alias, uri="http://10.8.21.165:19530", db_name="qi_wen_kb")
#         self.alias = alias

#     def close_connection(self):
#         """
#         关闭连接
#         """
#         connections.disconnect(self.alias)
#         return

#     @staticmethod
#     def add_document(collection_name: str, data: list):
#         """
#         添加文档
#         :param collection_name: 知识库名称
#         :param data: 需要入库的数据
#         :return:
#         """
#         collection = Collection(collection_name)
#         return collection.insert(data=data)

#     @staticmethod
#     def iterator_collection(batch_size: int, collection_name: str):
#         """
#         批量迭代集合中的所有元素
#         :param batch_size: 批大小
#         :param collection_name: 集合名称
#         :return: 返回迭代器
#         """
#         collection = Collection(collection_name)
#         return collection.query_iterator(batch_size=batch_size, output_fields=["*"])

#     @staticmethod
#     def query_by_condition_pagination(
#         collection_name: str,
#         search_condition="",
#         page=1,
#         page_size=0,
#         sort_field="index",
#         reverse=True,
#     ):
#         collection = Collection(collection_name)
#         # results = collection.query(
#         #     expr=search_condition,
#         #     order_by=f"{sort_field} {'DESC' if reverse else 'ASC'}",
#         #     offset=(page - 1) * page_size,
#         #     limit=page_size,
#         #     output_fields=["*"],
#         # )

#         iterator = collection.query_iterator(
#             batch_size=1000, expr=search_condition, output_fields=[sort_field, "index"]
#         )
#         results = []
#         while True:
#             result = iterator.next()
#             if not result:
#                 iterator.close()
#                 break
#             results += result
#         iterator.close()
#         total = len(results)
#         results.sort(key=lambda x: x["file_time"], reverse=reverse)
#         results = results[(page - 1) * page_size : page * page_size]
#         results = [i.get("index") for i in results]

#         results = collection.query(
#             expr=f"index in {results}",
#             output_fields=["*"],
#         )

#         return results, total

#     @staticmethod
#     def count_documents(collection_name: str, search_condition=""):
#         collection = Collection(collection_name)
#         total_count = 0
#         query_iterator = collection.query_iterator(
#             expr=search_condition,
#             batch_size=100,  # 不影响统计，仅用于分批查询
#             output_fields=["index"],  # 随便选一个字段（不影响计数）
#         )
#         while True:
#             batch = query_iterator.next()
#             if not batch:
#                 break
#             total_count += len(batch)
#         query_iterator.close()
#         return total_count


# class MilvusUtil(object):
#     """
#     Milvus工具类
#     """

#     def __init__(self):
#         """
#         连接数据库
#         :return:
#         """
#         # 获取连接配置
#         connect_config = MilvusConfig.MILVUS_CONNECT_INFO
#         if connect_config is None:
#             raise ValueError(f"向量数据库的连接配置未找到")
#         # 获得连接对象
#         self.milvus_client = AsyncMilvusClient(**connect_config)
#         self.flush_client = MilvusClient(**connect_config)

#     async def create_collection(
#         self, collection_name: str, kb_schema: CollectionSchema, kb_index: IndexParams
#     ):
#         """
#         创建知识库
#         :param collection_name: 知识库名称
#         :param kb_schema: 知识库结构
#         :param kb_index: 知识库索引
#         :return:
#         """
#         # 创建知识库
#         await self.milvus_client.create_collection(
#             collection_name=collection_name, schema=kb_schema, index_params=kb_index
#         )

#     async def drop_collection(self, collection_name: str):
#         """
#         删除知识库
#         :param collection_name: 知识库名称
#         :return:
#         """
#         # 删除知识库
#         await self.milvus_client.drop_collection(collection_name)

#     async def collection_is_exists(self, collection_name: str):
#         """
#         知识库是否存在
#         :param collection_name: 知识库名称
#         :return:
#         """
#         # 知识库是否存在
#         return self.milvus_client.has_collection(collection_name)

#     async def add_document(self, collection_name: str, data: list):
#         """
#         添加文档
#         :param collection_name: 知识库名称
#         :param data: 需要入库的数据
#         :return:
#         """
#         await self.milvus_client.insert(collection_name=collection_name, data=data)
#         self.flush_client.flush(collection_name=collection_name)

#     async def del_document(self, collection_name: str, del_conditions: str):
#         """
#         删除文档
#         :param collection_name: 知识库名称
#         :param del_conditions: 删除条件
#         :return:
#         """
#         await self.milvus_client.delete(
#             collection_name=collection_name, filter=del_conditions
#         )

#     async def query_by_scalar(
#         self, collection_name: str, query_conditions: str, **other_conditions: dict
#     ):
#         """
#         根据标量进行查询
#         :param collection_name: 知识库名称
#         :param query_conditions: 查询条件
#         :param other_conditions: 其它条件，如output_fields或limit等
#         :return:
#         """
#         # 根据标量查询文档
#         docs = await self.milvus_client.query(
#             collection_name=collection_name, filter=query_conditions, **other_conditions
#         )
#         return docs

#     async def document_is_exists(self, collection_name: str, query_conditions: str):
#         """
#         文档是否已经存在
#         :param collection_name: 知识库名称
#         :param query_conditions: 查询条件
#         :return:
#         """
#         # 限制条件
#         other_conditions = {"output_fields": ["pk"], "limit": 1}
#         # 查询文档
#         docs = await self.query_by_scalar(
#             collection_name=collection_name,
#             query_conditions=query_conditions,
#             **other_conditions,
#         )
#         if docs is None or docs == []:
#             return False
#         return True

#     async def search_by_vector(
#         self,
#         collection_name: str,
#         vector: list[list],
#         limit: int,
#         search_params: Optional[dict] = None,
#         **other_params: Optional[dict],
#     ):
#         """
#         根据向量进行查询
#         :param collection_name: 知识库名称
#         :param vector: 向量
#         :param limit: 条数限制
#         :param search_params: 查询参数
#         :param other_params: 其它参数，如output_fields
#         :return:
#         """
#         # 根据向量查询文档
#         # import pdb; pdb.set_trace()
#         docs = await self.milvus_client.search(
#             collection_name=collection_name,
#             data=vector,
#             limit=limit,
#             output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
#             search_params=search_params,
#             **other_params,
#         )
#         # LogUtil.info("知识库搜索结果：{}".format(docs))
#         # for doc in docs[0]:
#         #     LogUtil.info("知识库单片搜索结果：{}".format(doc))
#         #     doc["distance"] = 1 - doc["distance"]
#         #     if doc["distance"] < 0:
#         #         doc["distance"] = 0
#         return docs

#     async def rename_collection(self, old_name, new_name):
#         """
#         重命名集合
#         :param old_name: 旧名称
#         :param new_name: 新名称
#         """
#         if await self.milvus_client.has_collection(old_name):
#             await self.milvus_client.rename_collection(old_name, new_name)


if __name__ == "__main__":
    # 获得连接
    import asyncio

    # asyncio.run(main_py())
    # client = MilvusClient(uri="http://10.8.21.165:19530", db_name="qi_wen_kb")
    # res = client.search(
    #     collection_name="aaa",
    #     data=vector,
    #     limit=10,
    #     output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
    #     search_params={"metric_type": "L2", "parmas": {}},
    # )
    # print(f"res的类型：{type(res)}")
    # for item in res:
    #     pprint(item)

    # 创建与删除知识库
    # print(milvus_util.create_collection("jiu_ti"))
    # print(milvus_util.drop_collection("jiu_ti"))

    # 文档是否已经存在
    # params = "source == '{}'".format("体质问答6.28.docx")
    # print(milvus_util.document_is_exists("jiu_ti", params))

    # # 删除文档
    # params = "source == '{}'".format("体质问答6.28.docx")
    # milvus_util.del_document("jiu_ti", params)
