# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：knowledge_retrieval_service.py
@Author  ：zhou_min
@Date    ：2025/09/24
@Description: 统一的知识检索服务，整合了原有的复杂检索逻辑
"""

from typing import Any, Optional
from datetime import datetime

from bson import ObjectId
from loguru import logger

from base_configs.milvus_config import MilvusConfig
from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.embedding_util import EmbeddingUtil
from base_utils.milvus_util import MilvusUtil
from base_utils.mongodb_util import MongodbUtil
from base_utils.rerank_util import RerankUtil
from service_knowledge_manage.entity.knowledge_hub_entity import (
    KnowledgeEntity,
    KnowledgeRecallEntity,
    KnowledgeRetrivalInfo,
    KnowledgeRetrivalResponse,
)
from service_knowledge_manage.service.knowledge_service import KnowledgeService


# logger = loguru logger (auto-migrated)
class KnowledgeRetrievalService:
    """
    知识检索服务类

    统一管理知识库的检索逻辑，支持多种检索模式：
    - 语义检索（默认）：使用稠密向量进行语义相似度检索
    - 全文检索（fulltext）：优先使用稀疏向量检索，不支持则退回BM25检索
    - 混合检索：结合稠密向量和稀疏向量（或BM25）的混合检索
    - 支持重排序和增强检索
    """

    def __init__(self):
        """初始化知识检索服务"""
        self.milvus_util = None  # 延迟初始化，按需创建

    def _to_jsonable(self, obj):
        """将对象递归转换为原生可 JSON 序列化的类型。"""
        # 处理 Milvus Hit 对象（必须在字典处理之前）
        # Milvus 返回的搜索结果可能包含 Hit 对象，需要转换为字典
        if hasattr(obj, "__class__") and obj.__class__.__name__ == "Hit":
            # Hit 对象通常包含 id, distance, entity 等属性
            try:
                result = {
                    "id": getattr(obj, "id", None),
                    "distance": float(getattr(obj, "distance", 0)),
                    "entity": dict(getattr(obj, "entity", {})),
                }
                # 递归处理 entity 中的内容
                return self._to_jsonable(result)
            except Exception as e:
                from loguru import logger

                logger.warning(f"处理 Hit 对象失败: {e}")
                return {}

        # 字典
        if isinstance(obj, dict):
            return {self._to_jsonable(k): self._to_jsonable(v) for k, v in obj.items()}

        # 序列（但排除字符串/字节）
        from collections.abc import Sequence

        if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
            try:
                return [self._to_jsonable(x) for x in list(obj)]
            except TypeError:
                return [self._to_jsonable(x) for x in obj]

        # numpy/自定义数值
        try:
            # 处理 numpy 标量等
            import numpy as _np  # 本地导入，避免强依赖

            if isinstance(obj, (_np.floating,)):
                return float(obj)
            if isinstance(obj, (_np.integer,)):
                return int(obj)
        except Exception:
            pass
        # 尝试通用 float/int 转换
        try:
            if hasattr(obj, "__float__"):
                return float(obj)
        except Exception:
            pass
        try:
            if hasattr(obj, "__int__"):
                return int(obj)
        except Exception:
            pass

        return obj

    def _ensure_mongodb_connection(self):
        """确保MongoDB连接可用，与原路由文件保持一致"""
        # 直接调用连接，与原路由文件保持一致的方式
        MongodbUtil.connect()

    def _ensure_milvus_connection(self):
        """确保Milvus连接可用，按需初始化"""
        if self.milvus_util is None:
            self.milvus_util = MilvusUtil()
        return self.milvus_util

    async def advanced_knowledge_retrieval(self, params: KnowledgeRetrivalInfo) -> KnowledgeRetrivalResponse:
        """
        高级知识检索接口（用于替代原有的 knwolege_retrieval 函数）

        Args:
            params: 知识检索参数

        Returns:
            KnowledgeRetrivalResponse: 结构化的检索响应
        """
        logger.info(f"高级知识库检索入参：{params}")

        try:
            if not params.user_query:
                return KnowledgeRetrivalResponse(
                    user_query=params.user_query,
                    is_rerank=bool(params.rerank_id),
                    results=[],
                )

            if params.rerank_id:
                rerank_model_data = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(params.rerank_id),
                )
                if rerank_model_data:
                    params.rerank_model = rerank_model_data.get("model_uid", "") or params.rerank_model

            # 获取知识库信息
            kb_info = await self._get_knowledge_base_info(params.id)
            if not kb_info:
                raise ValueError("知识库不存在")

            # 执行检索
            docs = await self._execute_search(params, kb_info)


            if not docs:
                return KnowledgeRetrivalResponse(
                    user_query=params.user_query,
                    is_rerank=bool(params.rerank_id),
                    results=[],
                )

            # 构建初始结果
            chunks = self._build_initial_chunks(docs, params)

            # 应用重排序（如果需要）
            if params.rerank_id:
                results = await self._apply_rerank_processing(chunks, params, kb_info)
            else:
                results = await self._apply_recall_processing(chunks, params)

            return KnowledgeRetrivalResponse(
                user_query=params.user_query,
                is_rerank=bool(params.rerank_id),
                results=results,
            )

        except Exception:
            raise

    async def _get_knowledge_base_info(self, kb_id: str) -> Optional[dict[str, Any]]:
        """获取知识库信息"""
        # 确保MongoDB连接
        self._ensure_mongodb_connection()

        query_result = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.KB_COLLECTION, search_condition={"_id": ObjectId(kb_id)}
        )

        return query_result[0] if query_result else None

    async def _execute_search(self, params: KnowledgeRetrivalInfo, kb_info: dict[str, Any]) -> list[dict[str, Any]]:
        """执行搜索"""
        collection_name = "_" + str(params.id)
        search_type = getattr(params, "search_type", None)
        if not search_type:
            kb_info = await self._get_knowledge_base_info(params.id)
            search_type = kb_info.get("search_type", "semantic")

        if search_type == "fulltext":
            # 全文检索：优先使用稀疏向量，不支持则退回BM25
            embedding_util = EmbeddingUtil(embedding_id=kb_info["embedding_id"])
            model_id = kb_info.get("embedding_id", ModelConfig.DEFAULT_EMBEDDING_MODEL)
            model_data = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id=ObjectId(model_id),
            )
            if model_data:
                model_uid = model_data.get("model_uid", "")
            # 从知识库配置读取稀疏向量支持信息
            supports_sparse = kb_info.get("supports_sparse_vector", False)
            logger.info(f"从知识库配置读取稀疏向量支持状态: {supports_sparse}")

            milvus_util = self._ensure_milvus_connection()

            if supports_sparse:
                # 使用稀疏向量检索
                logger.info("使用稀疏向量进行全文检索")
                sparse_embeddings = embedding_util.get_embedding(
                    model_uid=model_uid,
                    input=params.user_query,
                    return_sparse=True,
                )

                # 确保使用正确的向量格式
                if isinstance(sparse_embeddings, list):
                    sparse_embeddings = sparse_embeddings[0]

                docs_result = await milvus_util.hybrid_search(
                    collection_name=collection_name,
                    query_sparse_model=sparse_embeddings,
                    output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
                    filter_expr=" chunk_split_type != 'parent' ",  # 过滤掉标记为父块的切片
                )
            else:
                # 退回到BM25检索
                logger.info("模型不支持稀疏向量，退回到BM25检索")
                docs_result = await milvus_util.hybrid_search(
                    collection_name=collection_name,
                    query_sparse_bm25=params.user_query,
                    output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
                    filter_expr=" chunk_split_type != 'parent' ",  # 过滤掉标记为父块的切片
                )

            docs = docs_result[0] if docs_result else []

        elif search_type == "hybrid":
            # 混合检索
            embedding_util = EmbeddingUtil(embedding_id=kb_info["embedding_id"])
            embedding_id=kb_info["embedding_id"]
            model_data = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id=ObjectId(embedding_id),
            )
            if model_data:
                model_uid = model_data.get("model_uid", "")

            embeddings = embedding_util.get_embedding(
                model_uid=model_uid,
                input=params.user_query,
                return_sparse=False,
            )

            # 确保使用正确的向量格式（兼容原始实现）
            if isinstance(embeddings, list):
                embeddings = embeddings[0]

            fusion_weights = getattr(params, "fusion_weights", [0.7, 0.3])

            milvus_util = self._ensure_milvus_connection()

            # 从知识库配置读取稀疏向量支持信息，决定使用稀疏向量还是BM25
            supports_sparse = kb_info.get("supports_sparse_vector", False)
            logger.info(f"混合检索使用稀疏向量支持状态: {supports_sparse}")

            if supports_sparse:
                # 使用稀疏向量 + 稠密向量混合检索
                sparse_embeddings = embedding_util.get_embedding(
                    model_uid=model_uid,
                    input=params.user_query,
                    return_sparse=True,
                )
                if isinstance(sparse_embeddings, list):
                    sparse_embeddings = sparse_embeddings[0]

                docs_result = await milvus_util.hybrid_search(
                    collection_name=collection_name,
                    query_dense_vector=embeddings,
                    query_sparse_model=sparse_embeddings,
                    weights=fusion_weights,
                    output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
                    filter_expr=" chunk_split_type != 'parent' ",  # 过滤掉标记为父块的切片
                )
            else:
                # 使用BM25 + 稠密向量混合检索
                docs_result = await milvus_util.hybrid_search(
                    collection_name=collection_name,
                    query_dense_vector=embeddings,
                    query_sparse_bm25=params.user_query,
                    weights=fusion_weights,
                    output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
                    filter_expr=" chunk_split_type != 'parent' ",  # 过滤掉标记为父块的切片
                )

            docs = docs_result[0] if docs_result else []

        else:
            # 默认语义检索
            embedding_util = EmbeddingUtil(embedding_id=kb_info["embedding_id"])
            model_id = kb_info.get("embedding_id", ModelConfig.DEFAULT_EMBEDDING_MODEL)
            model_data = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                doc_id=ObjectId(model_id),
            )
            if model_data:
                model_uid = model_data.get("model_uid", "")
            embeddings = embedding_util.get_embedding(
                model_uid=model_uid, input=params.user_query
            )
            # 确保使用正确的向量格式（兼容原始实现）
            if isinstance(embeddings, list):
                embeddings = embeddings[0]

            milvus_util = self._ensure_milvus_connection()
            docs_result = await milvus_util.hybrid_search(
                collection_name=collection_name,
                query_dense_vector=embeddings,
                output_fields=MilvusConfig.DEFAULT_MILVUS_OUTPUT_FIELDS,
                filter_expr=" chunk_split_type != 'parent' ",  # 过滤掉标记为父块的切片
            )
            docs = docs_result[0] if docs_result else []







        # 将子块替换为对应的父块
        docs = await self._replace_child_with_parent(docs, collection_name, milvus_util)
        docs = sorted(docs, key=lambda x: x["distance"], reverse=True)
        docs=docs[: params.recall_num]
        # 添加关联的图片url
        for docs_item in docs:
            if docs_item["entity"].get("source_data", ""):
                for item in docs_item["entity"]["source_data"]:
                    if item.get('src_node_type',"text") != "text":
                        file = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_id=docs_item["entity"]["file_id"]
                        )
                        if file.get("parse_result", ""):
                            for i in file["parse_result"]["result"]:
                                if item['src_node_id'] and i["id"] == item['src_node_id']:
                                    item["img_path"] = i["img_path"]
                                    break
        return docs  # 这里返回recall_num个父块

    async def _replace_child_with_parent(
        self, docs: list[dict[str, Any]], collection_name: str, milvus_util: MilvusUtil
    ) -> list[dict[str, Any]]:
        """
        将子块替换为对应的父块，并保留子块信息

        Args:
            docs: 原始检索结果
            collection_name: Milvus集合名称
            milvus_util: Milvus工具实例

        Returns:
            处理后的文档列表（子块已替换为父块，父块中包含子块信息）
        """
        processed_docs = []
        parent_chunk_map = {}  # 用于收集同一父块的所有子块信息

        # 第一遍：收集所有子块信息，按父块ID分组
        for doc in docs:
            entity = doc.get("entity", {})
            chunk_split_type = entity.get("chunk_split_type", "")
            if chunk_split_type == "child":
                parent_node = entity.get("parent_node", [])
                if parent_node:
                    parent_id = parent_node[0]
                    if parent_id not in parent_chunk_map:
                        parent_chunk_map[parent_id] = {"child_docs": [], "best_distance": float("-inf")}
                    parent_chunk_map[parent_id]["child_docs"].append(doc)
                    # 更新最佳距离（距离越大越好）
                    current_distance = doc.get("distance", 0)
                    if current_distance > parent_chunk_map[parent_id]["best_distance"]:
                        parent_chunk_map[parent_id]["best_distance"] = current_distance

        # 第二遍：处理所有文档
        for doc in docs:
            entity = doc.get("entity", {})
            chunk_split_type = entity.get("chunk_split_type", "")

            if chunk_split_type == "child":
                parent_node = entity.get("parent_node", [])
                if parent_node and parent_node[0] in parent_chunk_map:
                    parent_id = parent_node[0]
                    # 只处理第一个子块，避免重复
                    if doc == parent_chunk_map[parent_id]["child_docs"][0]:
                        # 从MongoDB中查询父块
                        try:
                            # 从MongoDB查询parent类型的数据
                            parent_docs = MongodbUtil.query_docs_by_condition(
                                collection_name=CollectionConfig.CHUNK_COLLECTION,
                                search_condition={"chunk_id": parent_id, "chunk_split_type": "parent"},
                            )

                            if parent_docs:
                                # 将父块数据转换为与原始docs相同的格式
                                parent_data = parent_docs[0]

                                # 为MongoDB数据添加index字段，使用number字段作为index
                                # 因为MongoDB中的parent数据没有index字段，但检索服务期望有这个字段
                                parent_data["index"] = parent_data.get("index", "")

                                # 净化 child_docs，确保可序列化
                                clean_child_docs = [
                                    self._to_jsonable(d) for d in parent_chunk_map[parent_id]["child_docs"]
                                ]

                                parent_doc = {
                                    "distance": parent_chunk_map[parent_id]["best_distance"],  # 使用最佳距离
                                    "entity": parent_data,  # 父块的数据
                                    "id": parent_data.get("index", doc.get("id", 0)),  # 使用父块的index作为id
                                    "child_docs": clean_child_docs,  # 添加子块信息（已净化）
                                }
                                processed_docs.append(parent_doc)
                        except Exception as e:
                            logger.warning(f"查询父块失败: {e}")
                            # 如果查询父块失败，保留原子块
                            processed_docs.append(doc)
            else:
                # 非子块（包括非parent类型）直接添加
                processed_docs.append(doc)

        # 返回前对整体结果进行净化，防止包含不可序列化类型
        return [self._to_jsonable(d) for d in processed_docs]

    def _build_initial_chunks(self, docs: list[dict[str, Any]], params: KnowledgeRetrivalInfo) -> list[KnowledgeEntity]:
        """构建初始chunks"""
        chunks = []

        for index, item in enumerate(docs, start=1):
            entity = item.get("entity", {})
            source_datas = entity.get("source_data", [])

            # 提取页码信息
            page = []
            for data in source_datas:
                src_page = data.get("src_node_page", "")
                if src_page and src_page not in page:
                    page.append(src_page)

            # 提取行信息
            row = []
            for data in source_datas:
                src_row = data.get("src_node_row", "")
                if src_row and src_row not in row:
                    row.append(src_row)

            filename = entity["file_name"]
            file_url = f"{params.id}/{filename}"

            chunk = KnowledgeEntity(
                recall_score=int(item["distance"] * 100) / 100.0,
                recall_index=index,
                chunk_content=entity["content"],
                file_name=filename,
                rerank_score=0,
                rerank_index=0,
                number=entity["number"],
                reference_node=source_datas,
                file_urls=file_url,
                page=page,
                row=row,
                file_id=entity["file_id"],
                child_docs=item.get("child_docs", []),  # 添加子块信息
                chunk_id=entity["chunk_id"]
            )
            chunks.append(chunk)

        return chunks

    async def _apply_rerank_processing(
        self, chunks: list[KnowledgeEntity], params: KnowledgeRetrivalInfo, kb_info: dict[str, Any]
    ) -> list[KnowledgeRecallEntity]:
        """应用重排序处理"""
        documents = [item.chunk_content for item in chunks]

        rerank_id = params.rerank_id if params.rerank_id else kb_info["rerank_id"]

        rerank_results = RerankUtil(rerank_id=rerank_id).socre_rerank(
            model_uid=params.rerank_model,
            documents=documents,
            query=params.user_query,
            top_n=params.rerank_num,
            return_documents=True,
            threshold=params.score,
        )

        # 处理重排序结果
        docs_only_contain_rerank = self._process_rerank_results(chunks, rerank_results)

        rerank_chunks = []
        for item in docs_only_contain_rerank:
            # 应用增强检索
            source_data = item.reference_node
            if params.enhance_rounds != 0:
                enhanced_result = await self._apply_chunk_enhancement(item, params, f"_{params.id}")
                item.chunk_content = enhanced_result["content"]
                item.page = enhanced_result["page"]
                item.row = enhanced_result["row"]
                source_data = enhanced_result["source_data"]

            # 获取文件路径信息
            file_paths = self._get_file_paths(item.file_id)

            rerank_chunk = KnowledgeRecallEntity(
                recall_score=int(item.rerank_score * 100) / 100.0,
                recall_index=item.rerank_index,
                chunk_content=item.chunk_content,
                file_name=item.file_name,
                number=item.number,
                reference_node=source_data,
                file_urls=item.file_urls,
                page=item.page,
                file_id=item.file_id,
                row=item.row,
                convert_path=file_paths["convert_path"],
                remove_image_path=file_paths["remove_image_path"],
                child_docs=item.child_docs,  # 保留子块信息
                chunk_id=item.chunk_id
            )
            # 缓存检索得到的引用节点，便于高亮接口按 chunk_id 读取
            try:
                self._cache_reference_node(kb_id=params.id, chunk_id=item.chunk_id, reference_node=source_data)
            except Exception as e:
                logger.warning(f"缓存 reference_node 失败（rerank）：{e}")
            rerank_chunks.append(rerank_chunk)

        return rerank_chunks

    async def _apply_recall_processing(
        self, chunks: list[KnowledgeEntity], params: KnowledgeRetrivalInfo
    ) -> list[KnowledgeRecallEntity]:
        """应用召回处理（无重排序）"""
        recall_datas = []

        for item in chunks:
            source_data = item.reference_node

            if params.enhance_rounds != 0:
                enhanced_result = await self._apply_chunk_enhancement(item, params, f"_{params.id}")
                item.chunk_content = enhanced_result["content"]
                item.page = enhanced_result["page"]
                item.row = enhanced_result["row"]
                source_data = enhanced_result["source_data"]

            # 获取文件路径信息
            file_paths = self._get_file_paths(item.file_id)

            recall_data = KnowledgeRecallEntity(
                chunk_content=item.chunk_content,
                file_name=item.file_name,
                number=item.number,
                recall_score=int(item.recall_score * 100) / 100.0,
                recall_index=item.recall_index,
                reference_node=source_data,
                file_urls=item.file_urls,
                page=item.page,
                file_id=item.file_id,
                row=item.row,
                convert_path=file_paths["convert_path"],
                remove_image_path=file_paths["remove_image_path"],
                child_docs=item.child_docs,  # 保留子块信息
                chunk_id=item.chunk_id
            )
            # 缓存检索得到的引用节点，便于高亮接口按 chunk_id 读取
            try:
                self._cache_reference_node(kb_id=params.id, chunk_id=item.chunk_id, reference_node=source_data)
            except Exception as e:
                logger.warning(f"缓存 reference_node 失败（recall）：{e}")
            recall_datas.append(recall_data)

        return recall_datas

    def _process_rerank_results(
        self, docs: list[KnowledgeEntity], rerank_results: list[dict[str, Any]]
    ) -> list[KnowledgeEntity]:
        """处理重排序结果"""
        # 修复：使用字典而非字典列表，便于快速查找
        content_to_data = {item.chunk_content: item for item in docs}
        sorted_results = sorted(rerank_results, key=lambda x: x["relevance_score"], reverse=True)

        docs_only_contain_rerank = []
        for rank, result in enumerate(sorted_results, start=1):
            content = result["document"]["text"]

            # 直接通过字典查找，保持排序顺序
            if content in content_to_data:
                matched_item = content_to_data[content]
                matched_item.rerank_score = result["relevance_score"]
                matched_item.rerank_index = rank
                docs_only_contain_rerank.append(matched_item)
                # 从字典中移除已处理的项，避免重复
                del content_to_data[content]
            else:
                logger.warning(f"未找到匹配的重排序内容: {content[:50]}...")

        return docs_only_contain_rerank

    async def _apply_chunk_enhancement(
        self, item: KnowledgeEntity, params: KnowledgeRetrivalInfo, collection_name: str
    ) -> dict[str, Any]:
        """应用chunk增强"""
        chunk_index = item.number
        chunk_file = item.file_name
        lower_bound = max(0, chunk_index - params.enhance_rounds)
        upper_bound = chunk_index + params.enhance_rounds

        expr = f"number >= {lower_bound} and number <= {upper_bound} and file_name == '{chunk_file}'"

        arrange_result=MongodbUtil.query_doc_by_id(CollectionConfig.KB_ARRANGE_INFO, ObjectId(collection_name[1:]))
        if arrange_result!=None and arrange_result.get("chunk_type","")=="parent":
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.CHUNK_COLLECTION,
                search_condition={"file_id": item.file_id,"number":{"$gte": lower_bound, "$lte": upper_bound}}
            )
        else:
            # expr = f"number >= {lower_bound} and number <= {upper_bound} and file_name == '{chunk_file}' and   chunk_split_type !=  "child"  "
            expr = (
                f"number >= {lower_bound} and number <= {upper_bound} and "
                f'file_name == "{chunk_file}" and '
                'chunk_split_type != "child"'
            )

            milvus_util = self._ensure_milvus_connection()
            result = await milvus_util.query_by_scalar(
                collection_name=collection_name,
                query_conditions=expr,
                output_fields=["content", "source_data", "number"],
            )

        chunks = []
        source_data = []
        result = sorted(result, key=lambda x: x["number"])

        for chunk in result:
            # 过滤纯图片或表格chunk
            if chunk.get("source_data"):
                is_image_or_table_only = len(chunk["source_data"]) == 1 and (
                    chunk["source_data"][0].get("src_ref_image") or chunk["source_data"][0].get("src_ref_table")
                )

                # if not is_image_or_table_only:
                chunks.append(chunk["content"])

                # 收集源数据
                for data in chunk["source_data"]:
                    if not any(
                        existing.get("src_node_id") == data.get("src_node_id")
                        for existing in source_data
                        if existing.get("src_node_id")
                    ):
                        source_data.append(data)
            else:
                chunks.append(chunk["content"])
        # 提取页码和行信息
        page = list({data.get("src_node_page") for data in source_data if data.get("src_node_page")})
        row = list({data.get("src_node_row") for data in source_data if data.get("src_node_row")})

        enhance_chunk = await KnowledgeService.merge_chunks_auto(chunks)

        if enhance_chunk == "":
            enhance_chunk = item.chunk_content
            page = item.page
            row = item.row
            source_data = item.reference_node

        return {
            "content": enhance_chunk,
            "page": page,
            "row": row,
            "source_data": source_data,
        }

    def _get_file_paths(self, file_id: str) -> dict[str, str]:
        """获取文件路径信息"""
        # 确保MongoDB连接
        self._ensure_mongodb_connection()

        file_info = MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, file_id)

        return {
            "convert_path": file_info.get("convert_path", "") if file_info else "",
            "remove_image_path": file_info.get("remove_image_path", "") if file_info else "",
        }

    def _cache_reference_node(self, kb_id: str, chunk_id: str, reference_node: list[dict[str, Any]]):
        """
        将检索得到的引用节点缓存到MongoDB，键为 (kb_id, chunk_id)。
        目的：前端不传 reference_node 时，高亮接口可通过 chunk_id 查到对应引用节点，保证一致性。

        Args:
            kb_id: 知识库ID
            chunk_id: 切片ID
            reference_node: 引用节点列表（通常来自 source_data）
        """
        try:
            # 连接MongoDB
            self._ensure_mongodb_connection()

            # 数据净化，确保可序列化
            clean_reference_node = self._to_jsonable(reference_node)

            # 采用 upsert 方式写入，避免重复
            MongodbUtil.find_one_and_update(
                collection_name=CollectionConfig.CHUNK_REFERENCE_NODE_COLLECTION,
                search_condition={"kb_id": ObjectId(kb_id), "chunk_id": chunk_id},
                replace_data={
                    "$set": {
                        "kb_id": ObjectId(kb_id),
                        "chunk_id": chunk_id,
                        "reference_node": clean_reference_node,
                        "updated_at": datetime.now(),
                    },
                    "$setOnInsert": {
                        "created_at": datetime.now(),
                    },
                },
            )
        except Exception as e:
            # 记录但不影响主流程
            logger.warning(f"写入引用节点缓存失败：{e}")


# 创建全局实例
knowledge_retrieval_service = KnowledgeRetrievalService()
