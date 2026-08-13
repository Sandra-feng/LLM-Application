#!/usr/bin/env python
"""
@Project    :   tiance-base
@File    :   knowledge_service.py
@Author  :   Shuo Shan
@Time    :   2024/09/11 09:31:39
"""

import hashlib
import io
from pymilvus import MilvusClient
# from utils.file_util import FileUtil
# from utils.minio_util import MinIoUtil
# from utils.milvus_util import MilvusUtil
# from configs.kb_config import KbConfig
# from configs.doc_config import DocConfig
# from service.text_seg_service import TextSegService
# from service.knowledge_service import KnowledgeService
# from service.text_embed_service import TextEmbedService
# from service.doc_loader_service import DocLoaderService
import os

import fitz
import minio
from bson import ObjectId
from loguru import logger
from pymupdf import JM_char_bbox, JM_rects_overlap, Quad, Rect
from starlette.concurrency import run_in_threadpool
from base_configs.milvus_config import MilvusConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.milvus_util import MilvusUtil
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from service_knowledge_manage.entity.knowledge_entity import KnowledgeInfo
from service_knowledge_manage.service.util.fuzzy_match import (
    JM_search_stext_page_v3,
    JM_search_stext_page_v4,
    fuzzy_match_template,
    quads_to_rect,
    split_text,
    string_of_page,
    suffix_prefix_match,
)


# logger = loguru logger (auto-migrated)
class KnowledgeService:
    _collection_name = CollectionConfig.KB_COLLECTION

    @staticmethod
    async def chunk_highlight_by_node(file_path: str, kb_id: str, chunk_id: str):
        """
        仅使用引用节点的坐标 bbox（*2 缩放）进行区域高亮，不做文本匹配。
        保留原有 MinIO 缓存检查、数据源获取与返回结构。
        """
        try:
            # 1) 已生成缓存检查
            full_file_name = file_path.split("/")[-1]
            if not full_file_name.endswith("pdf"):
                logger.error("文件不是pdf类型")
                raise fitz.FileDataError("文件不是pdf类型")
            file_name = os.path.splitext(full_file_name)[0]
            temp_highlight_path = f"highlight_pdf/{kb_id}_{file_name}/{chunk_id}/"
            if MinIoUtil.is_prefix_exist("tiance-base-temp-file-bucket", temp_highlight_path):
                # 如存在缓存，清理旧文件后重写，不引入新参数
                try:
                    old_files = MinIoUtil.get_file_list("tiance-base-temp-file-bucket", temp_highlight_path)
                    for entry in old_files:
                        obj_name = getattr(entry, "object_name", entry)
                        try:
                            MinIoUtil.delete_file("tiance-base-temp-file-bucket", obj_name)
                            logger.info(f"已删除旧高亮文件: {obj_name}")
                        except Exception as del_err:
                            logger.warning(f"删除旧高亮失败: {obj_name}, err={del_err}")
                except Exception as list_err:
                    logger.warning(f"列举旧高亮失败，继续重写: err={list_err}")

            # 2) 获取引用节点（优先使用检索后缓存的引用节点）
            cached = MongodbUtil.query_docs_by_condition(
                CollectionConfig.CHUNK_REFERENCE_NODE_COLLECTION,
                {"kb_id": ObjectId(kb_id), "chunk_id": chunk_id},
            )
            reference_node = []
            if cached:
                reference_node = cached[0].get("reference_node", [])
                logger.info(f"命中缓存的引用节点，kb_id={kb_id}, chunk_id={chunk_id}, 节点数={len(reference_node)}")

            # 若缓存未命中或为空，按原逻辑获取引用节点
            kb_chunk = MongodbUtil.query_doc_by_id(CollectionConfig.KB_ARRANGE_INFO, ObjectId(kb_id))
            if kb_chunk is None:
                # Milvus 查询
                collection_name = f"_{kb_id}"
                connect_config = MilvusConfig.MILVUS_CONNECT_INFO
                milvus_client = MilvusClient(**connect_config)
                result = milvus_client.has_collection(collection_name)
                if not result:
                    raise Exception("知识库对应的集合不存在")
                chunk_result = milvus_client.query(
                    collection_name=collection_name,
                    filter=f"chunk_id =='{chunk_id}'",
                    limit=1,
                )
                if not reference_node:
                    reference_node = chunk_result[0].get("source_data", [])
            else:
                chunk_method = kb_chunk.get("chunk_method")
                if chunk_method in ["parent_by_title", "parent_by_page", "parent_by_paragraph"]:
                    search_condition = {"knowledge_id": kb_id, "chunk_id": chunk_id}
                    chunk_result = MongodbUtil.query_docs_by_condition(
                        CollectionConfig.CHUNK_COLLECTION, search_condition
                    )
                    if not reference_node:
                        reference_node = chunk_result[0].get("source_data", [])
                else:
                    # Milvus 查询
                    collection_name = f"_{kb_id}"
                    connect_config = MilvusConfig.MILVUS_CONNECT_INFO
                    milvus_client = MilvusClient(**connect_config)
                    result = milvus_client.has_collection(collection_name)
                    if not result:
                        raise Exception("知识库对应的集合不存在")
                    chunk_result = milvus_client.query(
                        collection_name=collection_name,
                        filter=f"chunk_id =='{chunk_id}'",
                        limit=1,
                    )
                    if not reference_node:
                        reference_node = chunk_result[0].get("source_data", [])

            assert reference_node and len(reference_node) >= 1, "无引用块"

            # 3) 构造 r_nodes（bbox * 2，参考诊断脚本）
            r_nodes = []
            for item in reference_node:
                bbox = item.get("src_node_bbox")
                if not bbox or len(bbox) != 4:
                    logger.error(f"缺少或不合法的 bbox: {bbox}")
                    continue
                r_nodes.append(
                    {
                        "text": item.get("src_node_text"),
                        "bbox": [x * 2 for x in bbox],
                        "type": item.get("src_node_type"),
                        "page": item.get("src_node_page"),
                    }
                )

            if not r_nodes:
                raise Exception("引用节点解析失败：无合法 bbox 可用")

            # 4) 读取 PDF 并按坐标高亮（参考诊断脚本）
            if not MinIoUtil.exist_file("tiance-base", file_path):
                logger.info("找不到源文件")
                raise minio.S3Error
            response = await run_in_threadpool(MinIoUtil.min_io_client.get_object, "tiance-base", file_path)
            pdf_content = response.read()
            response.close()
            response.release_conn()
            pdf_file = io.BytesIO(pdf_content)
            doc = fitz.open(stream=pdf_file, filetype="pdf")

            for idx, node in enumerate(r_nodes):
                page_idx = int(node.get("page", 0))
                rect = node.get("bbox", [])
                page = doc.load_page(page_idx)
                max_x, max_y = page.rect.x1, page.rect.y1
                logger.info(f"[paint] idx={idx} page={page_idx+1} size=({max_x:.2f},{max_y:.2f}) bbox={rect}")
                if not rect or len(rect) != 4:
                    logger.error(f"节点 rect 不合法: {rect}")
                    continue
                if 0 <= rect[0] <= rect[2] <= max_x and 0 <= rect[1] <= rect[3] <= max_y:
                    page.add_highlight_annot(rect).update()
                else:
                    logger.error(
                        f"存在不合法高亮区域，页码={page_idx+1}, bbox={rect}, page_size=({max_x},{max_y})"
                    )

            # 5) 计算 page_num 与 chunk_coordinate（首节点页与 top）
            first_page_idx = int(r_nodes[0].get("page", 0))
            first_bbox_top = r_nodes[0].get("bbox", [0, 0, 0, 0])[1]
            page_ref = doc.load_page(first_page_idx)
            chunk_coordinate = page_ref.rect.y1 - first_bbox_top
            page_num = first_page_idx + 1

            # 6) 保存并上传结果到临时桶（沿用原路径格式）
            pdf_stream = io.BytesIO()
            doc.save(pdf_stream)
            pdf_stream.seek(0)
            file_path_highlight = (
                f"highlight_pdf/{kb_id}_{file_name}/{chunk_id}/{page_num}_{chunk_coordinate}/{file_name}_highlight.pdf"
            )
            write_result = MinIoUtil.min_io_client.put_object(
                "tiance-base-temp-file-bucket",
                file_path_highlight,
                pdf_stream,
                length=len(pdf_stream.getvalue()),
                content_type="application/pdf",
            )
            logger.info("成功上传高亮文件至Minio（诊断版坐标高亮）")
            return {
                "page_num": page_num,
                "chunk_coordinate": chunk_coordinate,
                "file_path_highlight": write_result.object_name,
            }
        except Exception as e:
            # 保持原有异常传播行为
            raise

    @staticmethod
    async def chunk_highlight(file_path: str, kb_id: str, chunk: str, page_list: list, abandon_area: dict):
        """
        高亮pdf中切片所在区域（仅文本）
        :param file_path: pdf文件的远程minio路径
        :param kb_id: 用于定位唯一的切片
        :param chunk: 切片文本
        :param page_list: 切片所在页码（1开头）
        :param abandon_area: 页眉页脚等区域的坐标rect
        :return: page_num: 切片第一个词所在页码，chunk_coordinate: 切片第一个词的y坐标，file_path_highlight: 高亮pdf文件的minio路径
        """
        try:
            # 使用chunk做唯一hash映射后的值为唯一chunk识别码
            chunk_uid = hashlib.sha256(chunk.encode("utf-8")).hexdigest()

            full_file_name = file_path.split("/")[-1]
            if not full_file_name.endswith("pdf"):
                logger.error("文件不是pdf类型")
                raise fitz.FileDataError("文件不是pdf类型")
            file_name = os.path.splitext(full_file_name)[0]
            temp_highlight_path = f"highlight_pdf/{kb_id}_{file_name}/{chunk_uid}/"
            if MinIoUtil.is_prefix_exist("tiance-base-temp-file-bucket", temp_highlight_path):
                # 如存在缓存，清理旧文件后重写，不引入新参数
                try:
                    old_files = MinIoUtil.get_file_list("tiance-base-temp-file-bucket", temp_highlight_path)
                    for entry in old_files:
                        obj_name = getattr(entry, "object_name", entry)
                        try:
                            MinIoUtil.delete_file("tiance-base-temp-file-bucket", obj_name)
                            logger.info(f"已删除旧高亮文件: {obj_name}")
                        except Exception as del_err:
                            logger.warning(f"删除旧高亮失败: {obj_name}, err={del_err}")
                except Exception as list_err:
                    logger.warning(f"列举旧高亮失败，继续重写: err={list_err}")

            # 从 MinIO 获取文件对象
            if not MinIoUtil.exist_file("tiance-base", file_path):
                logger.info("找不到源文件")
                raise minio.S3Error
            response = await run_in_threadpool(MinIoUtil.min_io_client.get_object, "tiance-base", file_path)
            # 读取文件内容到内存中
            pdf_content = response.read()
            # 关闭响应流
            response.close()
            response.release_conn()
            # 使用 io.BytesIO 将字节数据包装成文件对象
            pdf_file = io.BytesIO(pdf_content)
            # 使用 PyMuPDF 打开 PDF 文件
            doc = fitz.open(stream=pdf_file, filetype="pdf")
            page_list = sorted([item - 1 for item in page_list])
            # 页码一定是公差为1的等差序列
            assert len(page_list) < 2 or all(y - x == 1 for x, y in zip(page_list, page_list[1:])), (
                "页码参数不合法，应为公差为1的等差序列"
            )
            abandon_dict = {int(k) - 1: v for k, v in abandon_area.items()}
            # last_page = page_list[-1]
            # for p in reversed(page_list):
            #     if last_page == doc.page_count - 1:
            #         doc.fullcopy_page(p, -1)
            #         continue
            #     doc.fullcopy_page(p, last_page + 1)

            # cun_1 = string_of_page(doc.load_page(0).get_textpage().this)
            # 剔除pdf中的禁止区域
            logger.info("->剔除pdf中的禁止区域")
            page_dict = dict({})
            for page_num in page_list:
                page = doc.load_page(page_num)
                origin_page = page.get_textpage()
                ## 删除禁止区域文本
                # words = origin_page.extractWORDS()
                # for word in words:
                #     word_rect = fitz.Rect(word[:4])
                #     for ab_rect in abandon_dict.get(page_num, []):
                #         ab_rect_cp = ab_rect.copy()
                #         ab_rect_cp[1] = origin_page.rect[3] - ab_rect_cp[1]
                #         ab_rect_cp[3] = origin_page.rect[3] - ab_rect_cp[3]
                #         if word_rect.intersects(ab_rect_cp):
                #             page.add_redact_annot(word_rect)
                # 按字符级删除禁止区域文本
                for ab_rect in abandon_dict.get(page_num, []):
                    ab_rect[1] = origin_page.rect[3] - ab_rect[1]
                    ab_rect[3] = origin_page.rect[3] - ab_rect[3]
                del_page = doc.load_page(page_num).get_textpage().this
                for del_block in del_page:
                    for del_line in del_block:
                        for ch in del_line:
                            r = JM_char_bbox(del_line, ch)
                            for ab_rect in abandon_dict.get(page_num, []):
                                if JM_rects_overlap(r, Rect(ab_rect)):
                                    page.add_redact_annot(r)

                page.apply_redactions()
                page_dict[page_num] = page

            # 合并所有页
            logger.info("->合并所有页")
            char_join = ""
            for _, page_entity in page_dict.items():
                char_join += string_of_page(page_entity.get_textpage().this)

            # 模糊匹配目标串
            logger.info("->模糊匹配")
            begin, end = fuzzy_match_template(long_text=char_join, template=chunk, re_a=0.2, re_min=13, re_max=50)
            match_text = char_join[begin:end]
            # logger.info(f"匹配串：{repr(match_text)}")
            # 跨页高亮，获取每一页需要高亮的区域
            logger.info("->跨页高亮")
            quads_ans = JM_search_stext_page_v3(char_join, begin, end, page_dict)
            # 将quads转为rect
            for _, quads in quads_ans.items():
                if not quads:
                    continue
                items = len(quads)
                for i in range(items):
                    q = Quad(quads[i])
                    quads[i] = q.rect
                i = 0
                while i < items - 1:
                    v1 = quads[i]
                    v2 = quads[i + 1]
                    if v1.y1 != v2.y1 or (v1 & v2).is_empty:
                        i += 1
                        continue
                    quads[i] = v1 | v2
                    del quads[i + 1]
                    items -= 1
            # 将所有rect按页高亮
            # doc.delete_pages(reversed(page_list))
            # for page_num in reversed(page_list):
            #     doc.delete_page(page_num)
            # 重新读一边pdf文件

            response = await run_in_threadpool(MinIoUtil.min_io_client.get_object, "tiance-base", file_path)
            # 读取文件内容到内存中
            pdf_content = response.read()
            # 关闭响应流
            response.close()
            response.release_conn()
            # 使用 io.BytesIO 将字节数据包装成文件对象
            pdf_file = io.BytesIO(pdf_content)
            # 使用 PyMuPDF 打开 PDF 文件
            doc = fitz.open(stream=pdf_file, filetype="pdf")

            for page_num, rects in quads_ans.items():
                page_load = doc.load_page(page_num)
                max_x = page_load.rect.x1
                max_y = page_load.rect.y1
                for rect in rects:
                    if 0 <= rect.x0 < rect.x1 <= max_x and 0 <= rect.y0 < rect.y1 <= max_y:
                        # 高亮区域需合法
                        page_load.add_highlight_annot(rect).update()
                    else:
                        logger.info("存在不合法高亮区域，页码{}".format(page_num + 1))
            pdf_stream = io.BytesIO()
            doc.save(pdf_stream)
            pdf_content = pdf_stream.getvalue()
            # 重置流位置
            pdf_stream.seek(0)
            page_num = page_list[0]
            for k in reversed(page_list):
                if quads_ans.get(k):
                    page_num = k
            chunk_coordinate = doc.load_page(page_num).rect.y1 - quads_ans.get(page_num)[0].y0
            # 返回和存入minio的page_num需要回到以1开头的格式，需要加1
            page_num += 1
            file_path_highlight = (
                f"highlight_pdf/{kb_id}_{file_name}/{chunk_uid}/{page_num}_{chunk_coordinate}/{file_name}_highlight.pdf"
            )

            write_result = await run_in_threadpool(
                MinIoUtil.min_io_client.put_object,
                "tiance-base-temp-file-bucket",
                file_path_highlight,
                pdf_stream,
                length=len(pdf_content),
                content_type="application/pdf",
            )
            logger.info("->成功上传高亮文件至Minio")
            return {
                "page_num": page_num,
                "chunk_coordinate": chunk_coordinate,
                "file_path_highlight": write_result.object_name,
            }

        except Exception as e:
            raise

    @staticmethod
    async def kb_filename_delete(kb_name: str, file_folder: str):
        milvusUtil = MilvusUtil()
        results = await milvusUtil.query_by_scalar(collection_name=kb_name, query_conditions="", limit=10000)
        unique_files = []
        for result in results:
            file_name = result["file_name"]
            if file_name not in [item["file_name"] for item in unique_files]:
                unique_files.append({"file_name": file_name})
        logger.info(f"删除文件 {str(unique_files)}")
        bucket_name = "tiance-base"
        for item in unique_files:
            MinIoUtil.remove_file(bucket_name, item["file_name"])
        # 删除知识库
        await milvusUtil.drop_collection(kb_name)
        # 删除信息库表
        MongodbUtil.del_docs_by_condition(KnowledgeService._collection_name, {"kb_name": kb_name})

        return "Knowledge base deleted successfully"

    # @staticmethod
    # async def query_kb_by_embedding_model(embedding_model: str):
    #
    #     # 通过嵌入模型名称embedding，获取知识库
    #     kbs = MongodbUtil.query_docs_by_condition(
    #         collection_name=KnowledgeService._collection_name,
    #         search_condition={"embedding_model": embedding_model},
    #     )
    #     kbs_result = []
    #     for item in kbs:
    #         item["_id"] = str(item["_id"])
    #         kbs_result.append(item)
    #
    #     return kbs_result

    @staticmethod
    async def get_all_emb_model_info():
        """
        返回所有嵌入模型列表
        """
        try:
            models = MongodbUtil.query_docs_by_condition(
                CollectionConfig.MODEL_RUN_COLLECTION,
                {"model_type": "embedding", "status": "running"},
            )
            emb_model_list = []
            for model in models:
                emb_model_list.append(
                    {
                        "embedding_model": model["_id"],
                        "dimension": model["embedding_dimension"],
                    }
                )
            return emb_model_list
        except:
            raise

    @staticmethod
    async def slice_retrieval_update(
        id: str,
        rerank_model: str,
        retrieval_count: int,
        score: float,
        top_k: int,
        rerank_id: str,
        enhance_rounds: int,
        search_type: str,
        fusion_weights: list[float],
    ):
        try:
            MongodbUtil.update_docs_by_condition(
                KnowledgeService._collection_name,
                search_condition={"_id": ObjectId(id)},
                replace_data={
                    "$set": {
                        "retrieval_count": retrieval_count,
                        "rerank_model": rerank_model,
                        "top_k": top_k,
                        "score": score,
                        "rerank_id": rerank_id,
                        "enhance_rounds": enhance_rounds,
                        "search_type": search_type,
                        "fusion_weights": fusion_weights,
                    }
                },
            )
        except:
            raise

    @staticmethod
    async def is_in_agent_list(kb_id: str, account_id: str):
        try:
            agent_name_list = []
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.ARRANGE_AGENT_COLLECTION,
                search_condition={"kb_list": {"$in": [kb_id]}, "account_id": account_id},
            )
            for _ in result:
                agent_name = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.AGENT_COLLECTION,
                    doc_id=ObjectId(str(_["_id"])),
                )["agent_name"]
                agent_name_list.append(agent_name)
            if agent_name_list:
                return agent_name_list
            return False
        except:
            raise

    @staticmethod
    async def update_kb_name_in_workflow(kb_id: str, new_name: str):
        try:
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,
                search_condition={
                    "workflow_graph.nodes": {
                        "$elemMatch": {
                            "type": "knowledge",
                            "data.kb_list": {"$elemMatch": {"_id": kb_id}},
                        }
                    }
                },
            )
            for item in result:
                logger.info(f"查询到配置该知识库的工作流ID:{item['_id']}")
                workflow_arrange = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,
                    doc_id=item["_id"],
                )
                new_workflow_arrange = workflow_arrange.copy()
                for index_node in range(len(workflow_arrange["workflow_graph"]["nodes"])):
                    if workflow_arrange["workflow_graph"]["nodes"][index_node]["type"] == "knowledge":
                        for index_kb in range(
                            len(workflow_arrange["workflow_graph"]["nodes"][index_node]["data"]["kb_list"])
                        ):
                            if (
                                workflow_arrange["workflow_graph"]["nodes"][index_node]["data"]["kb_list"][index_kb][
                                    "_id"
                                ]
                                == kb_id
                            ):
                                new_workflow_arrange["workflow_graph"]["nodes"][index_node]["data"]["kb_list"][
                                    index_kb
                                ]["kb_name"] = new_name
                MongodbUtil.replace_docs_by_condition(
                    collection_name=CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,
                    search_condition={"_id": item["_id"]},
                    replace_data=new_workflow_arrange,
                )
            return True
        except Exception as e:
            raise

    @staticmethod
    async def is_in_workflow_list(kb_id: str, account_id: str):
        try:
            workflow_name_list = []
            result = MongodbUtil.query_docs_by_condition(
                CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,
                search_condition={
                    "workflow_graph.nodes": {
                        "$elemMatch": {
                            "type": "knowledge",
                            "data.kb_list": {"$elemMatch": {"_id": kb_id}},
                        }
                    }
                },
            )
            for _ in result:
                workflow_name = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.WORKFLOW_COLLECTION,
                    doc_id=ObjectId(str(_["_id"])),
                )["workflow_name"]
                workflow_name_list.append(workflow_name)
            if workflow_name_list:
                return workflow_name_list
            return False
        except:
            raise

    @staticmethod
    async def is_knowledge_exist(search_condition: dict):
        """
        检查知识库是否存在
        """
        result = MongodbUtil.query_docs_by_condition(CollectionConfig.KB_COLLECTION, search_condition=search_condition)
        for i in result:
            return True
        return False

    @staticmethod
    async def _check_sparse_vector_support(embedding_util, model_uid: str) -> bool:
        """
        检查嵌入模型是否支持稀疏向量生成

        Args:
            embedding_util: 嵌入工具实例
            model_uid: 模型ID

        Returns:
            bool: 是否支持稀疏向量生成
        """
        try:
            # 使用测试文本检查稀疏向量支持，使用静默模式避免日志污染
            test_input = "测试稀疏向量支持"
            sparse_result = embedding_util.get_embedding(
                model_uid=model_uid,
                input=test_input,
                return_sparse=True,
                silent_on_error=True,  # 静默模式，不记录异常日志
            )

            # 检查返回结果是否为有效的稀疏向量
            if sparse_result and len(sparse_result) > 0:
                sparse_vector = sparse_result[0] if isinstance(sparse_result, list) else sparse_result
                # 稀疏向量应该是字典格式 {index: value, ...}
                if isinstance(sparse_vector, dict) and len(sparse_vector) > 0:
                    logger.info(f"模型 {model_uid} 支持稀疏向量生成")
                    return True

            logger.debug(f"模型 {model_uid} 不支持稀疏向量生成（返回结果无效）")
            return False

        except Exception as e:
            # 这是预期的情况，使用debug级别记录，避免污染日志
            logger.debug(f"模型 {model_uid} 不支持稀疏向量生成: {type(e).__name__}")
            return False

    @staticmethod
    async def kb_create(knowledge_info: KnowledgeInfo, account_id: str):
        """
        创建知识库
        :param knowledge_info: 知识库信息
        :param account_id: 账户ID
        :return: (是否成功, 消息, 知识库ID)
        """
        mongo_result = None
        milvus_created = False
        collection_name = None

        try:
            # 提取知识库基本信息
            kb_name = knowledge_info.kb_name
            description = knowledge_info.description
            embedding_model = knowledge_info.embedding_model
            embedding_dimension = knowledge_info.embedding_dimension
            embedding_id = knowledge_info.embedding_id
            rerank_id = knowledge_info.rerank_id
            team_code = knowledge_info.team_code
            embedding_max_tokens = knowledge_info.embedding_max_tokens

            # 参数验证
            if embedding_dimension <= 0:
                return False, "嵌入维度必须大于0", None

            if len(kb_name.strip()) == 0:
                return False, "知识库名称不能为空", None

            # 初始化嵌入工具和Milvus工具
            from base_utils.embedding_util import EmbeddingUtil

            embeddingUtil = EmbeddingUtil(embedding_id=embedding_id)
            milvusUtil = MilvusUtil()

            # 检查嵌入模型是否支持稀疏向量
            logger.info(f"检查嵌入模型 {embedding_model} 是否支持稀疏向量生成")
            supports_sparse_vector = await KnowledgeService._check_sparse_vector_support(embeddingUtil, embedding_model)
            logger.info(f"模型 {embedding_model} 稀疏向量支持状态: {supports_sparse_vector}")

            # 先进行mongodb数据库入库操作，根据入库后得到的id作为向量知识库表名称
            mongo_result = MongodbUtil.insert_one(
                KnowledgeService._collection_name,
                {
                    "kb_name": kb_name,
                    "description": description,
                    "embedding_model": embedding_model,
                    "embedding_dimension": embedding_dimension,
                    "retrieval_count": 10,
                    "embedding_id": embedding_id,
                    "rerank_id": rerank_id,
                    "rerank_model": "",
                    "top_k": 5,
                    "score": 0.5,
                    "account_id": account_id,
                    "team_code": team_code,
                    "prompt": "",
                    "is_rerank": "",
                    "supports_sparse_vector": supports_sparse_vector,  # 存储稀疏向量支持信息
                    "max_tokens": embedding_max_tokens,
                    "search_type": "semantic",  # 默认使用语义检索
                    "chunk_type": 1,
                },
            )

            # 生成向量数据库集合名称
            collection_name = "_" + str(mongo_result.inserted_id)
            logger.info(f"--> 生成的知识库id为：{str(mongo_result.inserted_id)}")

            # 创建支持混合检索的向量数据库集合
            await milvusUtil.create_hybrid_collection(
                collection_name=collection_name,
                dense_dim=embedding_dimension,  # 修正参数名称
                enable_bm25=True,  # 支持BM25全文检索
                enable_model_sparse=supports_sparse_vector,  # 根据模型实际支持情况决定是否启用稀疏向量
            )
            milvus_created = True

            return True, "创建知识库成功", mongo_result.inserted_id

        except Exception as e:
            logger.exception(f"创建知识库失败: {str(e)}")

            # 错误回滚机制
            try:
                # 回滚向量数据库操作
                if milvus_created and collection_name:
                    await milvusUtil.drop_collection(collection_name)
                    logger.info(f"已回滚向量数据库集合: {collection_name}")

                # 回滚MongoDB操作
                if mongo_result:
                    MongodbUtil.del_doc_by_id(KnowledgeService._collection_name, mongo_result.inserted_id)
                    logger.info(f"已回滚MongoDB文档: {mongo_result.inserted_id}")

            except Exception as rollback_error:
                logger.error(f"回滚操作失败: {str(rollback_error)}", exc_info=True)

            # 返回具体错误信息
            error_msg = f"创建知识库失败: {str(e)}"
            return False, error_msg, None

    @staticmethod
    async def kb_delete(knowledge_id: str):
        try:
            # 先获取知识库中的文件
            file_list = []
            results = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                search_condition={"knowledge_id": knowledge_id},
            )
            for result in results:
                file_name = result["file_name"]
                file_list.append(file_name)
            logger.info(f"删除文件 {file_list}")

            # 删除Minio的知识库文件
            bucket_name = "tiance-base"
            file_path = knowledge_id
            for file in file_list:
                # 删除Minio文件
                MinIoUtil.remove_file(bucket_name, file, file_path)

            # 删除milvus知识库文件
            milvusUtil = MilvusUtil()
            await milvusUtil.drop_collection("_" + knowledge_id)

            # 删除知识库id的知识库信息
            MongodbUtil.del_docs_by_condition(KnowledgeService._collection_name, {"_id": ObjectId(knowledge_id)})

            # 删除知识库id的知识库中所有上传文件的信息
            MongodbUtil.del_docs_by_condition(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"knowledge_id": knowledge_id},
            )

            return True, "知识库删除成功"

        except Exception as e:
            raise

    async def kb_update(knowledge_id: str, kb_name: str, description: str, team_code: str):
        try:
            old_kb_name = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.KB_COLLECTION,
                doc_id=ObjectId(knowledge_id),
            )["kb_name"]
            if kb_name != old_kb_name:
                await KnowledgeService.update_kb_name_in_workflow(knowledge_id, kb_name)
                replace_data = {
                    "$set": {
                        "description": description,
                        "team_code": team_code,
                        "kb_name": kb_name,
                    }
                }
            else:
                replace_data = {"$set": {"description": description, "team_code": team_code}}
            MongodbUtil.update_docs_by_condition(
                KnowledgeService._collection_name,
                search_condition={"_id": ObjectId(knowledge_id)},
                replace_data=replace_data,
            )
            return True
        except:
            raise

    @staticmethod
    async def get_all_kb(condition=None):
        """
        添加了新的参数condition, dict类型, 用于添加查询条件, 默认为{}, 即查询所有数据
        返回所有符合条件的知识库列表
        """
        try:
            if condition is None:
                condition = {}
            kb_list = []
            knowledge_list = MongodbUtil.query_docs_by_condition(KnowledgeService._collection_name, condition)

            knowledge_list = list(knowledge_list)
            for knowledge in knowledge_list:
                kb_list.append(knowledge)

            result = []
            for item in reversed(kb_list):
                item["id"] = str(item.pop("_id"))
                result.append(item)
            return result, len(result)

        except Exception as e:
            raise

    @staticmethod
    async def get_kb_pagination(condition=None, page=1, page_size=0):
        """
        分页查询知识库
        """
        try:
            if condition is None:
                condition = {}
            kb_list = []
            kb_q = MongodbUtil.query_docs_by_condition_pagination(
                KnowledgeService._collection_name,
                condition,
                page,
                page_size,
                sort_field="_id",
                reverse=True,
            )

            for doc in kb_q:
                doc["id"] = str(doc.pop("_id"))
                kb_list.append(doc)
            kb_len = MongodbUtil.count_documents_by_condition(KnowledgeService._collection_name, condition)
            return kb_list, kb_len

        except Exception as e:
            raise

    @staticmethod
    async def get_kb_describe(knowledge_id: str):
        try:
            result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.KB_COLLECTION,
                search_condition={"_id": ObjectId(knowledge_id)},
            )

            for i in result:
                return i["description"]

            return ""
        except:
            raise

    @staticmethod
    async def knowledge_describe(knowledge_id: str):
        try:
            # 获取切片数量
            milvusUtil = MilvusUtil()
            results = await milvusUtil.query_by_scalar(
                collection_name="_" + knowledge_id,
                query_conditions="chunk_split_type != 'parent'",
                limit=16380,
                output_fields=["index"],
            )

            # 获取文件列表
            file_list = MongodbUtil.query_docs_by_condition(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"knowledge_id": knowledge_id},
            )

            kb_result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.KB_COLLECTION,
                search_condition={"_id": ObjectId(knowledge_id)},
            )
            for kb in kb_result:
                prompt = kb["prompt"]
                retrieval_count = kb["retrieval_count"]
                rerank_model = kb["rerank_model"]
                top_k = kb["top_k"]
                score = kb["score"]
                rerank_id = kb["rerank_id"]
                enhance_rounds = kb.get("enhance_rounds", 0)
                max_tokens = kb.get("max_tokens", None)
                search_type = kb.get("search_type", "semantic")
                fusion_weights = kb.get("fusion_weights", [0.7, 0.3])
                is_rerank = kb.get("is_rerank", False)
            return (
                len(list(file_list)),
                len(results),
                knowledge_id,
                prompt,
                retrieval_count,
                rerank_model,
                top_k,
                score,
                rerank_id,
                enhance_rounds,
                max_tokens,
                search_type,
                fusion_weights,
                is_rerank,
            )

        except Exception:
            raise

    async def find_max_overlap(a: str, b: str) -> int:
        """找到字符串 a 的结尾 和 b 的开头之间的最大重叠长度"""
        max_len = min(len(a), len(b))
        for i in range(max_len, 0, -1):
            if a[-i:] == b[:i]:
                return i
        return 0

    async def merge_chunks_auto(chunks: list[str]) -> str:
        if not chunks:
            return ""
        merged = chunks[0]
        for i in range(1, len(chunks)):
            overlap_len = await KnowledgeService.find_max_overlap(merged, chunks[i])
            merged += chunks[i][int(overlap_len) :]  # 仅拼接非重叠部分
        return merged

    @staticmethod
    async def download_minio_folder(bucket_name: str, prefix: str, local_folder: str):
        try:
            os.makedirs(local_folder, exist_ok=True)
            objects = MinIoUtil.get_file_list(bucket_name, prefix=prefix)
            for object_name in objects:
                remote_file_path = object_name
                file_name = os.path.basename(remote_file_path)
                if file_name:
                    local_file_path = os.path.join(local_folder, remote_file_path[len(prefix) :])
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    MinIoUtil.download_file(bucket_name, remote_file_path, local_file_path)
                    logger.info(f"获取到的 MinIO 远程文件为：{remote_file_path}，下载到本地的路径为：{local_file_path}")
                else:
                    local_folder_path = os.path.join(local_folder, remote_file_path[len(prefix) :])
                    os.makedirs(local_folder_path, exist_ok=True)
                    logger.info(f"创建本地文件夹：{local_folder_path}")
                    await KnowledgeService.download_minio_folder(bucket_name, remote_file_path, local_folder_path)
        except Exception as e:
            raise

    @staticmethod
    async def ori_chunk_result(kb_id: str, chunk_id: str):
        """获取指定切片的原始内容（修复集合名称匹配问题）"""
        try:
            kb_chunk = MongodbUtil.query_doc_by_id(CollectionConfig.KB_ARRANGE_INFO, ObjectId(kb_id))
            if kb_chunk is None:
                collection_name = f"_{kb_id}"
                connect_config = MilvusConfig.MILVUS_CONNECT_INFO
                milvus_client = MilvusClient(**connect_config)
                result = milvus_client.has_collection(collection_name)
                if not result:
                    raise Exception(f"知识库对应的集合不存在")
                # 调用Milvus查询方法（参考milvus_collection_rename.py中的query用法）
                results = milvus_client.query(
                    collection_name=collection_name,
                    filter=f"chunk_id =='{chunk_id}'",
                    output_fields=["content"],
                    limit=1
                )
                if not results:
                    raise Exception(f"知识库[{kb_id}]中未找到chunk_id为{chunk_id}的切片")
                return {"ori_chunk": results[0]["content"]}
            else:
                chunk_method = kb_chunk.get("chunk_method")
                if chunk_method in ["parent_by_title", "parent_by_page", "parent_by_paragraph"]:
                    search_condition = {"knowledge_id": kb_id, "chunk_id": chunk_id}
                    chunk_result = MongodbUtil.query_docs_by_condition(CollectionConfig.CHUNK_COLLECTION, search_condition)
                    results = chunk_result[0].get("ori_content", "")
                    return {"ori_chunk": results }
                else:
                    collection_name = f"_{kb_id}"
                    connect_config = MilvusConfig.MILVUS_CONNECT_INFO
                    milvus_client = MilvusClient(**connect_config)
                    result = milvus_client.has_collection(collection_name)
                    if not result:
                        raise Exception(f"知识库对应的集合不存在")
                    # 调用Milvus查询方法（参考milvus_collection_rename.py中的query用法）
                    results = milvus_client.query(
                        collection_name=collection_name,
                        filter=f"chunk_id =='{chunk_id}'",
                        output_fields=["content"],
                        limit=1
                    )
                if not results:
                    raise Exception(f"知识库[{kb_id}]中未找到chunk_id为{chunk_id}的切片")
                return {"ori_chunk": results[0]["content"]}
        except Exception as e:
            raise  # 抛出原始异常，由路由层统一处理
if __name__ == "__main__":
    pass
    # doc = fitz.open(filename="D:\\xwechat_files\\wxid_i9wdwficrdy732_206b\\msg\\file\\2025-09\\克明食品扭亏隐忧 - 副本.pdf",
    #     filetype="pdf")
    # page_load = doc.load_page(6)
    # ye = [page_load.rect.x0, page_load.rect.y0, page_load.rect.x1, page_load.rect.y1]
    # area = [50.5, 296, 246.5, 311]
    # area2 = [50, 319.5, 219, 327]
    # weight = [100, 595, 490, 620]
    # print(ye)
    # origin_page = page_load.get_textpage().this
    # for block in origin_page:
    #     for line in block:
    #         for ch in line:
    #             r = JM_char_bbox(line, ch)
    #             pass
