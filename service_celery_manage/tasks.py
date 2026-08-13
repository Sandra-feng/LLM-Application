import asyncio
import time

from loguru import logger

from data_access.implementations.minio_repository import MinioRepository
from data_access.implementations.mongo_repository import MongoRepository
from service_knowledge_manage.service.util.file_progress import set_progress

mongo_client = MongoRepository()
mongo_client.connect()
minio_client = MinioRepository()
minio_client.connect()
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil

MongodbUtil.initialize(mongo_client)
MinIoUtil.initialize(minio_client)
# 尝试从 asgiref 导入；若缺失则提供轻量后备实现
# try:
#     from asgiref.sync import async_to_sync
# except ImportError:  # 运行环境未安装 asgiref 时的兜底
#     import asyncio
#     def async_to_sync(awaitable):
#         def _callable(*args, **kwargs):
#             return asyncio.run(awaitable(*args, **kwargs))
#         return _callable
from bson import ObjectId

from base_configs.api_config import ApiConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from service_knowledge_manage.service.knowledge_file_service import Knowledge_File_service
from service_knowledge_manage.service.parse_service import FileParseService
from service_knowledge_manage.service.splitter_service import SplitterService

from .celery_app import celery_app


# logger = loguru logger (auto-migrated)
@celery_app.task(name="file_parse_task")
def file_parse_task(
    local_path,
    knowledge_id,
    request_data,
    file_name,
    file_id,
    preview_mode,
    remote_path,
    chunk_method,
    chunk_size,
    chunk_overlap,
    separator,
    is_generate,
    multimodal_id,
    is_header_config,
    start_line,
    end_line,
    header_merge_method,
    is_content_merge,
    is_save_image,
    use_force_separator,
    chunk_type,
    sub_chunk_size,
    sub_separator
):
    try:
        set_progress(file_id, "0", 0, time.time())
        file_parse = FileParseService()

        # ===================== 更新状态：文档提取中 (2) =====================
        try:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 2}},
            )
        except Exception:
            pass

        # ===================== 构造 mock_request =====================
        class SimpleRequest:
            def __init__(self, data):
                self.__dict__.update(data or {})

        mock_request = SimpleRequest(request_data)

        # ===================== 获取 multimodal 配置 =====================
        if multimodal_id:
            model_info = MongodbUtil.query_doc_by_id(CollectionConfig.MODEL_RUN_COLLECTION, ObjectId(multimodal_id))
            model_uid = model_info.get("model_uid", "")
            api_url = model_info.get("api_url", f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1")
            api_key = model_info.get("api_key", "not empty")
            is_external = model_info.get("is_external", False)
        else:
            model_uid, api_url, api_key, is_external = "", "", "", False

        # ===================== 调用解析服务 =====================
        result = asyncio.run(
            file_parse.parse_file(
                local_path,
                knowledge_id,
                mock_request,
                file_name=file_name,
                file_id=file_id,
                chunk_method=chunk_method,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=separator,
                preview_mode=preview_mode,
                multimodal_id=multimodal_id,
                is_header_config=is_header_config,
                start_line=start_line,
                end_line=end_line,
                header_merge_method=header_merge_method,
                is_content_merge=is_content_merge,
                is_save_image=is_save_image,
                is_preview=False,
                model_uid=model_uid,
                api_url=api_url,
                api_key=api_key,
                is_external=is_external,
            )
        )

        # ===================== 写入解析结果 & 状态更新 =====================
        if result:
            status = result["status"]
            if status.lower() != "success":
                file_info = MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, file_id)
                if file_info["status"] != 3:
                    logger.info(f"文件{file_name}解析失败")
                    MongodbUtil.update_one(
                        CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                        {"_id": file_id},
                        {"$set": {"status": 3, "info": "文件解析失败"}},
                    )
        else:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 3, "info": "文件解析失败"}},
            )
        try:
            content_list = result["results"]["content_list"]
        except:
            return None
        set_progress(file_id, "0", 100, time.time())

        # 解析预览模式下，直接执行临时桶文件转移到正式桶
        if preview_mode:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"remote_path": f"{knowledge_id}/{file_name}"}},
            )
            MinIoUtil.copy_object(
                "tiance-base-temp-file-bucket",
                remote_path,
                "tiance-base",
                f"{knowledge_id}/{file_name}",
            )

        # Excel/CSV 文件处理
        if file_name.endswith((".xls", ".xlsx", ".csv")):
            if preview_mode:
                MongodbUtil.update_one(
                    CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                    {"_id": file_id},
                    {"$set": {"status": 4}},
                )
            MongodbUtil.insert_one(
                CollectionConfig.FILE_PARSE_RESULT,
                {"_id": file_id, "parse_result": content_list},
            )
            result = content_list

            # 其他文件（如 PDF/Doc 等）
        else:
            pdf_path = ""
            convert_path = ""
            if result["results"].get("transform_path"):
                # 取 transform_path 的第一个路径
                # pdf_path = next(iter(result["results"]["transform_path"].values()), "")
                pdf_paths = result["results"].get("transform_path").values()
                if pdf_paths:
                    pdf_path = next(iter(pdf_paths))
                    for item in pdf_paths:
                        if item.endswith("layout.pdf"):
                            pdf_path = item
                            break
                convert_path = next(iter(result["results"]["transform_path"].values()), "")

            update_data = {}
            if pdf_path:
                update_data["layout_path"] = pdf_path
            if convert_path:
                update_data["convert_path"] = convert_path
            if preview_mode:
                update_data["status"] = 4

            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": update_data},
            )
            MongodbUtil.insert_one(
                CollectionConfig.FILE_PARSE_RESULT,
                {"_id": file_id, "parse_result": {"result": content_list}},
            )
            result = {"result": content_list}

        if not preview_mode:
            status = MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, file_id)["status"]
            logger.info(f"知识库id为{knowledge_id}下的文件{file_name}解析状态为{status}")
            if status == 3:
                logger.info(f"{file_name}解析失败，直接跳过切块入库")
                return None
            # 更新状态
            try:
                MongodbUtil.update_one(
                    CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                    {"_id": file_id},
                    {"$set": {"status": 5}},
                )
            except Exception as e:
                logger.warning(f"更新文件 {file_id} 状态失败: {e}")

            # 取出解析结果
            result = (
                MongodbUtil.query_doc_by_id(CollectionConfig.FILE_PARSE_RESULT, file_id)
                .get("parse_result", {})
                .get("result", [])
            )

            # 切块 + 向量化
            asyncio.run(
                split_embedding_task(
                    result,
                    knowledge_id,
                    file_id,
                    file_name,
                    remote_path,
                    chunk_method,
                    chunk_size,
                    chunk_overlap,
                    separator,
                    is_generate,
                    use_force_separator,
                    chunk_type,
                    sub_chunk_size,
                    sub_separator
                )
            )

            # 文件从临时桶转移到正式桶
            MinIoUtil.copy_object(
                "tiance-base-temp-file-bucket",
                remote_path,
                "tiance-base",
                f"{knowledge_id}/{file_name}",
            )
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"remote_path": f"{knowledge_id}/{file_name}"}},
            )
        logger.info(f"文件 {file_name}({file_id}) 处理完成")

    except Exception as e:
        logger.exception(f"文件解析失败: {str(e)}")
        # ===================== 更新状态：文档提取失败 (3) =====================
        try:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 3, "info": str(e)}},
            )
        except Exception:
            logger.exception(f"更新文件 {file_id} 状态失败")
            pass


async def split_embedding_task(
    parse_result,
    knowledge_id,
    file_id,
    file_name,
    remote_path,
    chunk_method,
    chunk_size,
    chunk_overlap,
    separator,
    is_generate,
    use_force_separator,
    chunk_type=None,
    sub_chunk_size=None,
    sub_separator=None,
):
    try:
        # 状态：切分入库中(6)
        try:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 6}},
            )
        except Exception:
            pass
        chunks = None
        # 如果解析结果已经是切片，直接返回
        splitter_service = SplitterService()
        set_progress(file_id, "1", 0, time.time())
        if isinstance(parse_result, dict):
            try:
                parse_list = parse_result["result"]
            except Exception as e:
                logger.error("解析文件异常失败", exc_info=True)
                return None
            chunks = await splitter_service.split_text_simple(
                text=parse_list,
                method=chunk_method,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=separator,
                is_embedding=True,
                use_force_separator=use_force_separator,
                chunk_type=chunk_type,
                sub_chunk_size=sub_chunk_size,
                sub_separator=sub_separator,
            )
        elif isinstance(parse_result, list):
            try:
                chunks = await splitter_service.split_text_simple(
                    text=parse_result,
                    method=chunk_method,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    separator=separator,
                    is_embedding=True,
                    use_force_separator=use_force_separator,
                    chunk_type=chunk_type,
                    sub_chunk_size=sub_chunk_size,
                    sub_separator=sub_separator,
                )
            except Exception as e:
                MongodbUtil.update_one(
                    CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                    {"_id": file_id},
                    {"$set": {"status": 7, "info": str(e)}},
                )
                return None
        set_progress(file_id, "1", 100, time.time())

    except Exception as e:
        MongodbUtil.update_one(
            CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
            {"_id": file_id},
            {"$set": {"status": 7, "info": str(e)}},
        )
        logger.exception(f"文件切片失败: {str(e)}")
        raise
    try:
        if chunks is None:
            logger.info("文件解析失败")
        error_info = None
        # set_progress(file_id, "0", 100.0, time.time())
        # 向量化入库
        try:
            if is_generate:
                result = await Knowledge_File_service.add_embedding_document(
                    knowledge_id,
                    chunks,
                    file_name,
                    file_id,
                )
            else:
                result, info = await Knowledge_File_service.add_embedding_document_without_question(
                    knowledge_id,
                    chunks,
                    file_name,
                    file_id,

                )
        except Exception as e:
            logger.exception("文件切分入库失败")
            error_info = str(e)
            result = None

        # 更新文件状态
        if result:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 0}},
            )

            # 复制文件到正式存储（remote_path 可能为空，做保护）
            if remote_path:
                MongodbUtil.update_one(
                    CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                    {"_id": file_id},
                    {"$set": {"remote_path": f"{knowledge_id}/{file_name}"}},
                )
        else:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 7, "info": error_info}},
            )

    except Exception as e:
        logger.exception(f"处理单个文件失败: {file_name}")
        # 状态：切分入库失败(7)
        try:
            MongodbUtil.update_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {"_id": file_id},
                {"$set": {"status": 7, "info": str(e)}},
            )
        except Exception:
            logger.exception(f"更新文件 {file_id} 状态失败")
            pass
