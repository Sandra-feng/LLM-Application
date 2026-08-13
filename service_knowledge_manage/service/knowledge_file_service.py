
import asyncio
import datetime
import json
import os
import re
import time
import zipfile
from typing import Optional
from collections import Counter
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse
from collections import defaultdict
import aiofiles
import py7zr
from bson import ObjectId
from celery.result import AsyncResult
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from base_configs.api_config import ApiConfig
from base_configs.minio_config import MinioConfig
from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.embedding_util import EmbeddingUtil
from base_utils.milvus_util import MilvusUtil
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from service_agent_manage.service.agent_service import AgentService
from service_celery_manage.celery_app import celery_app
from service_knowledge_manage.service.util.file_progress import set_progress
from service_model_manage.service.chat_completion_service import OpenAILLMService
from service_permission_auth.entity.usr_auth_entity import UsrEntity
from service_permission_auth.service.usr_auth_service import UsrAuthService
from service_usr_manage.service.snow_util import generate_unique_id


# logger = loguru logger (auto-migrated)
def find_pages_for_chunk(chunk_text, page_boundaries, full_text):
    chunk_text = chunk_text.replace("\n", "")
    full_text = full_text.replace("\n", "")
    idx = full_text.find(chunk_text)
    if idx == -1:
        return []  # 找不到
    end_idx = idx + len(chunk_text)
    result = []
    for page_num, start, end in page_boundaries:
        if start < end_idx and end > idx:
            result.append(page_num)
    return result


def decode_filename(filename):
    """
    解码文件名
    :param filename: 文件名
    :return: 解码后的文件名
    """
    try:
        # 尝试用 utf-8 编码解码文件名
        decoded_filename = filename.encode("cp437").decode("gbk")
        return decoded_filename
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    try:
        # 尝试用 cp437 编码解码文件名，然后转换为 gbk 编码
        decoded_filename = filename.encode("utf-8").decode("utf-8")
        return decoded_filename
    except (UnicodeDecodeError, UnicodeEncodeError):
        pass

    # 如果所有编码都失败，返回原始文件名
    return filename


class Knowledge_File_service:
    """
    知识库文件服务
    """

    @staticmethod
    async def metadata_info_edit(id, new_content, file_id):
        try:
            parse_result = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_id=file_id
            ).get("parse_result", {"result": []})["result"]
            for index in range(len(parse_result)):
                if parse_result[index]["id"] == id:
                    parse_result[index]["text"] = new_content
            MongodbUtil.update_docs_by_condition(
                collection_name=CollectionConfig.FILE_PARSE_RESULT,
                search_condition={"_id": file_id},
                replace_data={"$set": {"parse_result.result": parse_result}},
            )
            logger.info(f"文件{file_id}元数据信息编辑成功")
            return True
        except Exception as e:
            raise

    @staticmethod
    async def get_multimodal_info():
        multimodal_id = ""
        internal_model, external_model = await Knowledge_File_service.get_multimodal_model()
        for item in internal_model["children"]:
            multimodal_id = item["id"]
            break
        if multimodal_id == "":
            for item in external_model["children"]:
                multimodal_id = item["id"]
                break
        if multimodal_id:
            model_info = MongodbUtil.query_doc_by_id(CollectionConfig.MODEL_RUN_COLLECTION, ObjectId(multimodal_id))
            model_uid = model_info.get("model_uid", "")
            api_url = model_info.get("api_url", f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1")
            api_key = model_info.get("api_key", "not empty")
            is_external = model_info.get("is_external", False)
        else:
            model_uid, api_url, api_key, is_external = "", "", "", False
        return multimodal_id, model_uid, api_url, api_key, is_external

    @staticmethod
    async def delete_metadata_info(file_id, id):
        try:
            final_result = []
            parse_result = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_id=file_id
            ).get("parse_result", {"result": []})["result"]
            for index in range(len(parse_result)):
                if parse_result[index]["id"] == id:
                    continue
                final_result.append(parse_result[index])
            MongodbUtil.update_docs_by_condition(
                collection_name=CollectionConfig.FILE_PARSE_RESULT,
                search_condition={"_id": file_id},
                replace_data={"$set": {"parse_result.result": final_result}},
            )
            logger.info(f"文件{file_id}元数据信息删除成功")
            return True
        except Exception as e:
            raise

    @staticmethod
    async def update_parse_result(file_id, data):
        """
        上传文件并返回文件本地地址
        :return:
        """
        try:
            parse_result = MongodbUtil.query_doc_by_id(CollectionConfig.FILE_PARSE_RESULT, file_id)["parse_result"][
                "result"
            ]
            for item in data:
                content_id = item["id"]
                new_content = item["text"]
                for content_index in range(len(parse_result)):
                    if parse_result[content_index]["id"] == content_id:
                        parse_result[content_index]["text"] = new_content
                        break
            MongodbUtil.update_docs_by_condition(
                CollectionConfig.FILE_PARSE_RESULT,
                {"_id": file_id},
                replace_data={"$set": {"parse_result.result": parse_result}},
            )
            return "解析内容修改成功"

        except:
            raise

    @staticmethod
    async def get_parse_result_by_file_id(file_id):
        """
        上传文件并返回文件本地地址
        :return:
        """
        try:
            parse_result = MongodbUtil.query_doc_by_id(CollectionConfig.FILE_PARSE_RESULT, file_id).get(
                "parse_result", {}
            )
            is_save_image = MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, file_id).get(
                "is_save_image", False
            )
            return {"parse_result": parse_result, "is_save_image": is_save_image}

        except:
            raise

    @staticmethod
    async def get_multimodal_model():
        try:
            internal_model = []
            external_model = []
            models = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                search_condition={"model_type": "LLM", "status": "running", "is_external": False},
            )
            for model in models:
                if "modalities" in model and "image" in model["modalities"]:
                    model_info = {
                        "id": str(model["_id"]),
                        "model_uid": model.get("model_uid", ""),
                        "model_name": model.get("model_uid", ""),
                    }

                    internal_model.append(model_info)
            logger.info(f"内部多模态模型数量为{len(internal_model)}")

            models = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                search_condition={"model_type": "LLM", "status": "running", "is_external": True},
            )
            for model in models:
                if "modalities" in model and "image" in model["modalities"]:
                    model_info = {
                        "id": str(model["_id"]),
                        "model_uid": model.get("model_uid", ""),
                        "model_name": model["model_name"] if model.get("model_name", None) else model["model_uid"],
                    }

                    external_model.append(model_info)
            logger.info(f"外部多模态模型数量为{len(internal_model)}")

            return {"name": "内部", "children": internal_model}, {"name": "外部", "children": external_model}
        except:
            raise

    @staticmethod
    async def agent_upload_file(file_obj, account_id):
        """
        上传文件并返回文件本地地址
        :return:
        """
        try:
            from base_configs.minio_config import MinioConfig

            local_paths = []
            file_name = file_obj.filename
            upload_path = Path(__file__).parents[2] / "upload"
            local_path = f"{upload_path}/{file_name}"
            file_type = Path(file_name).suffix.lstrip(".")

            # 读取文件内容
            file_content = await file_obj.read()  # 只读取一次
            file_size = len(file_content)

            # 格式化文件大小
            # formatted_size = f"{file_size:.2f} {'B'}"

            # 异步写入文件内容
            async with aiofiles.open(local_path, "wb") as temp_file:
                await temp_file.write(file_content)  # 写入之前读取的内容
            local_paths.append(local_path)
            # 上传文件到 MinIO
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            remote_path = f"{account_id}/workflow/{timestamp}-{file_name}"  # 可以根据需求修改路径或文件名
            bucket_name = MinioConfig.BUCKET_NAME
            await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, local_path)
            remote_path = f"http://{MinioConfig.END_POINT}/{MinioConfig.BUCKET_NAME}/{remote_path}"
            data = {"name": file_name, "size": file_size, "mini_type": file_type, "url": remote_path}

            type_mapping = {
                "document": ["xlsx", "xls", "xlsd", "docx", "doc", "pdf", "txt", "ppt", "md", "csv", "pptx", "html"],
                "image": ["png", "jpg"],
                "audio": ["mp3", "m4a", "wav", "webm", "arm", "mpga"],
                "video": ["mp4", "mov", "mpeg", "mpga"],
            }

            # 获取文件类型（file_type）
            file_extension = data["mini_type"]

            # 根据映射关系确定type值，默认为"unknown"
            file_type_category = "unknown"
            for category, extensions in type_mapping.items():
                if file_extension.lower() in extensions:  # 转为小写进行比较
                    file_type_category = category
                    break
            # 将新的字段type添加到data字典中
            data["type"] = file_type_category
            result = {"code": 200, "message": "Success", "status": True, "data": data}
            return result

        except (Exception, RuntimeError) as e:
            raise

        finally:
            for local_path in local_paths:
                if os.path.exists(local_path):
                    os.remove(local_path)

    """
    知识库文件服务
    """

    @staticmethod
    async def agent_upload_from_url(url, account_id):
        """
        从文件URL下载文件并上传到MinIO，返回文件信息
        :param url: 文件URL
        :param account_id: 用户ID
        :return: 文件信息
        """
        local_paths = []
        try:
            from datetime import datetime

            import aiohttp

            parsed_url = urlparse(url)
            path_segments = parsed_url.path.strip("/").split("/")
            filename = path_segments[-1] if path_segments else "unknown_file"
            url_extension = os.path.splitext(filename)[1].lower()
            upload_path = Path(__file__).parents[2] / "upload"
            upload_path.mkdir(parents=True, exist_ok=True)

            max_retries = 2
            retry_delay = 0.1

            for attempt in range(max_retries):
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(url) as response:
                            if response.status != 200:
                                if response.status == 404:
                                    return {
                                        "code": 404,
                                        "message": "文件未找到，请检查URL是否正确",
                                        "status": False,
                                        "data": {"error": "file_not_found"},
                                    }
                                else:
                                    return {
                                        "code": response.status,
                                        "message": f"下载文件时发生错误，状态码: {response.status}",
                                        "status": False,
                                        "data": {"error": "download_error"},
                                    }

                            file_content = await response.read()
                            if not file_content:
                                await asyncio.sleep(retry_delay)
                                continue

                            # 魔数检测
                            def detect_by_magic(content):
                                magic_map = {
                                    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": ".doc",  # DOC
                                    b"\x50\x4b\x03\x04": ".docx",  # DOCX
                                    b"\x50\x4b\x03\x04\x14\x00\x06\x00": ".xlsx",  # XLSX
                                    b"\x09\x08\x10\x00\x00\x06\x05\x00\x00\x00\x00\x00\x00\x00": ".xls",  # XLS
                                    b"\x50\x4b\x03\x04\x14\x00\x08\x00\x08\x00": ".pptx",  # PPTX
                                    b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1": ".ppt",  # PPT
                                    b"\x25\x50\x44\x46": ".pdf",  # PDF
                                    b"\x89PNG\r\n\x1a\n": ".png",  # PNG
                                    b"\xff\xd8\xff": ".jpg",  # JPG
                                    b"\xff\xd8\xff\xe0": ".jpg",  # JPG
                                    b"\xff\xd8\xff\xe1": ".jpg",  # JPG
                                    b"\xff\xd8\xff\xe2": ".jpg",  # JPG
                                    b"GIF87a": ".gif",  # GIF
                                    b"GIF89a": ".gif",  # GIF
                                    b"\x42\x4d": ".bmp",  # BMP
                                    b"\x00\x00\x01\x00": ".ico",  # ICO
                                    b"\x47\x49\x46\x38": ".gif",  # GIF
                                    b"\x49\x49": ".tif",  # TIF
                                    b"\x89\x50\x4e\x47": ".png",  # PNG
                                    b"\x52\x49\x46\x46": ".wav",  # WAV
                                    b"\x50\x4b\x03\x04": ".zip",  # ZIP
                                    b"\x52\x61\x72\x21\x1a\x07\x00": ".rar",  # RAR
                                    b"\x37\x7a\xbc\xaf\x27\x1c": ".7z",  # 7-Zip
                                    b"\x75\x73\x74\x61\x72": ".tar",  # TAR
                                }
                                for magic, ext in magic_map.items():
                                    if content.startswith(magic):
                                        return ext
                                return None

                            magic_extension = detect_by_magic(file_content)

                            # Content-Type 检测
                            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
                            mime_map = {
                                "application/pdf": ".pdf",
                                "image/png": ".png",
                                "image/jpeg": ".jpg",
                                "image/gif": ".gif",
                                "image/bmp": ".bmp",
                                "image/x-icon": ".ico",
                                "image/tiff": ".tif",
                                "image/svg+xml": ".svg",
                                "audio/wav": ".wav",
                                "application/x-dll": ".dll",
                                "application/zip": ".zip",
                                "application/x-rar-compressed": ".rar",
                                "application/x-7z-compressed": ".7z",
                                "application/x-tar": ".tar",
                                "application/vnd.ms-excel": ".xls",
                                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
                                "application/msword": ".doc",
                                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
                                "application/vnd.ms-powerpoint": ".ppt",
                                "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
                                "image/vnd.adobe.photoshop": ".psd",
                                "audio/midi": ".mid",
                                "application/x-shockwave-flash": ".swf",
                                "video/x-flv": ".flv",
                                "video/mp4": ".mp4",
                                "video/quicktime": ".mov",
                                "video/x-ms-wmv": ".wmv",
                                "audio/x-ms-wma": ".wma",
                                "application/vnd.ms-cab-compressed": ".cab",
                                "application/x-msdownload": ".exe",
                                "application/x-rar": ".rar",
                                "application/java-archive": ".jar",
                                "application/x-zlib": ".zlib",
                                "application/x-sdf": ".sdf",
                                "text/x-solution-file": ".sln",
                            }
                            content_type_extension = mime_map.get(content_type)

                            # 文件扩展名判断逻辑
                            if url_extension in [".doc", ".ppt", ".docx", ".pptx"]:
                                final_extension = url_extension
                            else:
                                extensions = [magic_extension, url_extension, content_type_extension]
                                non_none_extensions = [ext for ext in extensions if ext is not None]

                                if non_none_extensions:
                                    count = Counter(non_none_extensions)
                                    most_common = count.most_common()

                                    if most_common and most_common[0][1] >= 2:
                                        final_extension = most_common[0][0]
                                    else:
                                        final_extension = (
                                            magic_extension or url_extension or content_type_extension or ".bin"
                                        )
                                else:
                                    final_extension = (
                                        magic_extension or url_extension or content_type_extension or ".bin"
                                    )

                            # 文件格式白名单检查
                            supported_extensions = [
                                ".png",
                                ".jpg",
                                ".xlsx",
                                ".xls",
                                ".doc",
                                ".docx",
                                ".pdf",
                                ".txt",
                                ".ppt",
                                ".md",
                                ".csv",
                                ".pptx",
                                ".html",
                            ]
                            if final_extension not in supported_extensions:
                                return {
                                    "code": 400,
                                    "message": f"不支持的文件格式: {final_extension}，请上传支持的文件格式",
                                    "status": False,
                                    "data": {"error": "unsupported_file_format"},
                                }

                            # 文件存储逻辑
                            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")[:-3]
                            file_name = f"{timestamp}{final_extension}"
                            file_size = len(file_content)
                            local_path = upload_path / file_name
                            local_paths.append(local_path)
                            async with aiofiles.open(local_path, "wb") as f:
                                await f.write(file_content)

                            remote_path = f"{account_id}/workflow/{file_name}"
                            await run_in_threadpool(
                                MinIoUtil.upload_file, MinioConfig.BUCKET_NAME, remote_path, str(local_path)
                            )
                            remote_url = f"http://{MinioConfig.END_POINT}/{MinioConfig.BUCKET_NAME}/{remote_path}"

                            type_mapping = {
                                "document": ["pdf", "txt", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "csv", "rtf"],
                                "image": ["png", "jpg", "jpeg", "gif", "bmp", "ico", "svg", "webp"],
                                "archive": ["zip", "rar", "7z", "tar"],
                                "audio": ["mp3", "wav"],
                                "video": ["avi", "mpg", "flv"],
                                "other": ["dwg", "eml", "msg"],
                            }
                            ext = final_extension.lstrip(".").lower()
                            file_category = next((cat for cat, exts in type_mapping.items() if ext in exts), "unknown")

                            return {
                                "code": 200,
                                "message": "Success",
                                "status": True,
                                "data": {
                                    "name": file_name,
                                    "size": file_size,
                                    "mini_type": ext,
                                    "url": remote_url,
                                    "type": file_category,
                                },
                            }

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    await asyncio.sleep(retry_delay)
                    continue

            return {
                "code": 500,
                "message": "文件下载多次失败，请检查URL是否正确",
                "status": False,
                "data": {"error": "multiple_download_failures"},
            }

        except Exception as e:
            raise
        finally:
            for path in local_paths:
                try:
                    if path.exists():
                        path.unlink(missing_ok=True)
                except Exception as e:
                    raise

    @staticmethod
    async def get_upload_file(kb_name, file_name, file_obj, account_id):
        """
        上传文件并返回文件本地地址
        :return:
        """
        try:
            result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                search_condition={"kb_name": kb_name, "file_name": file_name, "account_id": account_id},
            )
            if len(list(result)) > 0:
                return False
            upload_path = Path(__file__).parents[2] / "upload"
            local_path = f"{upload_path}/{account_id}$$${kb_name}$$${file_name}"
            # 异步写入文件内容
            async with aiofiles.open(local_path, "wb") as temp_file:
                content = await file_obj.read()
                await temp_file.write(content)

            # 上传文件到 MinIO
            remote_path = f"{account_id}/{kb_name}/{file_name}"  # 可以根据需求修改路径或文件名
            bucket_name = MinioConfig.BUCKET_NAME
            await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, local_path)
            return local_path

        except (Exception, RuntimeError) as e:
            raise

    async def get_upload_file_multimode(file_name, file_obj, account_id):
        """
        上传文件并返回文件本地地址
        :return:
        """
        try:
            upload_path = Path(__file__).parents[2] / "upload"
            local_path = f"{upload_path}/{file_name}"
            # 异步写入文件内容
            async with aiofiles.open(local_path, "wb") as temp_file:
                content = await file_obj.read()
                await temp_file.write(content)

            # 上传文件到 MinIO
            from datetime import datetime

            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            remote_path = f"/multimode/{timestamp}-{file_name}"  # 可以根据需求修改路径或文件名
            bucket_name = MinioConfig.BUCKET_NAME
            await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, local_path)
            remote_path = f"/{MinioConfig.BUCKET_NAME}{remote_path}"
            return remote_path

        except:
            raise

        finally:
            if os.path.exists(local_path):
                os.remove(local_path)

    # @staticmethod
    # async def embedding_add_document(
    #     kb_name: str,
    #     doc: str,
    #     file_name: str,
    #     account_id: str = None,
    #     chunk_method: str = None,
    #     chunk_size: int = 500,
    #     chunk_overlap: int = 50,
    #     separator: str = "/n",
    # ):
    #     try:
    #         query_result = MongodbUtil.query_docs_by_condition(
    #             collection_name=CollectionConfig.KB_COLLECTION,
    #             search_condition={"kb_name": kb_name, "account_id": account_id},
    #         )
    #         if query_result:
    #             for i in query_result:
    #                 embedding_model = i["embedding_model"]
    #                 embedding_id = i["embedding_id"]
    #         else:
    #             logger.info("嵌入模型配置错误！")
    #             return False
    #
    #         if chunk_method == "RecursiveCharacterTextSplitter":
    #             textsplitter = RecursiveCharacterTextSplitter(
    #                 chunk_size=chunk_size, chunk_overlap=chunk_overlap, separators=["\n"], length_function=len
    #             )
    #         elif chunk_method == "SpacyTextSplitter":
    #             textsplitter = SpacyTextSplitter(
    #                 chunk_size=chunk_size, chunk_overlap=chunk_overlap, separator="\n", pipeline="zh_core_web_sm"
    #             )
    #         else:
    #             textsplitter = CharacterTextSplitter(separator="\n", chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    #
    #         if file_name.endswith(".csv"):
    #             chunks = [i.page_content for i in doc]
    #
    #         else:
    #             docs = doc[0].page_content
    #             chunks = textsplitter.split_text(docs)
    #
    #         logger.info(f"切块数量:{len(chunks)}")
    #         logger.info(f"切块内容:{chunks}")
    #         embeddingUtil = EmbeddingUtil(embedding_id)
    #         embeddings = embeddingUtil.get_embedding(model_uid=embedding_model, input=chunks)
    #         # embedding_model = HuggingFaceBgeEmbeddings(model_name="/root/bge-large-zh-v1.5")
    #         # embeddings = embedding_model.embed_documents(chunks)
    #
    #         result, file_id = await Knowledge_File_service.insert_file_info(kb_name, file_name, account_id)
    #         if result == False:
    #             logger.info("文档信息入库失败")
    #             return False
    #         logger.info("文档信息入库成功")
    #
    #         data = []
    #         upload_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    #         for i in range(len(chunks)):
    #             data.append(
    #                 {
    #                     "file_name": file_name,
    #                     "file_id": file_id,
    #                     "file_time": upload_time,
    #                     "number": i + 1,
    #                     "content": chunks[i],
    #                     "vector": embeddings[i],
    #                 }
    #             )
    #         milvus = MilvusUtil()
    #         collection_name = kb_name + "_" + str(account_id) if account_id else kb_name
    #         await milvus.add_document(collection_name=collection_name, data=data)
    #         logger.info("知识库添加文件成功")
    #         return True
    #     except (Exception, RuntimeError) as e:
    #         raise

    @staticmethod
    async def generate_question_answer(chunk_content):
        try:
            system_prompts = """
                你将接收到一段文本。请根据这段文本生成一个相关的问题。
                
                以下是你需要遵循的步骤：
                1. 输出结果尽量不超过十五个字，不需要携带思考过程。
                2. 输出结果不需要反复揣度字数限制的要求。
                3. 输出且仅输出一个相关的问题，除此之外，不要输出其他任何文本片段内容。
                4. 仔细阅读并理解提供的文本内容。
                5. 确定文本的主要主题和关键信息点。
                6. 根据文本内容，生成且只生成一个相关的问题，这个问题应该能够概括文本的核心内容或引发对文本主题的深入思考。
                7. 如果文本过长，可以先将文本内容简化为1000个字符以内的文本内容再进行问题生成。
                
                文本片段:
                "{TEXT}"
                
                输出结果：
                "{QUESTION}"
                
                示例：
                文本片段: "太阳是地球的主要能源来源，太阳的能量驱动了气候和天气系统。太阳能通过光合作用支持植物生长，进而为其他生物提供能量。"
                输出结果：
                "太阳对地球生态系统的哪些方面产生了重要影响？"
                
                文本片段: "人工智能（AI）是计算机科学的一个分支，致力于使机器能够执行通常需要人类智慧的任务，如语音识别、决策、翻译等。"
                输出结果：
                "人工智能在模拟人类智慧方面有哪些主要应用？"
                
                文本片段: "{"回答":"脑供血不足的常见调理干预方式：\\n1.中医内调：通过中药调理气血，改善血液循环。\\n2.外养方法：如针灸、推拿、拔罐等，帮助疏通经络，改善气血运行。\\n3.体质调理：血瘀体质可通过活血化瘀的饮食和药物进行改善，少阴、厥阴体质可通过调理新陈代谢和气血运行来改善。\\n4.生活习惯调整：保持规律作息，避免熬夜，适量运动，改善血液循环。\\n5.情绪管理：减轻压力，保持心情愉悦，避免长期紧张和焦虑。"}"
                输出结果：
                "脑供血不足可以通过哪些方法进行调理和干预？"
                
                文本片段: "{"回答":"脑供血不足是指大脑血液供应不足，导致脑细胞缺氧和营养物质缺乏的一种状态。大脑是人体最“耗能”的器官，每100克大脑组织每分钟至少需要40~60毫升的动脉血来提供能量。当脑血管出现问题（如动脉硬化、血栓、颈椎病等），或血液供应减少（如低血压、贫血等），大脑就会出现供血不足的现象。"}"
                输出结果：
                "脑供血不足是如何影响大脑功能和人体健康的？"

                """
            chunk_content = chunk_content.replace("\\n", " ").replace("\n", " ")
            system_prompts = system_prompts.replace("{TEXT}", chunk_content)
            id, model = await AgentService.get_first_running_model()  # 获取运行中的大模型
            openAILLMService = OpenAILLMService(id=id)
            logger.info(f"调用的大模型id为{id}, 调用的大模型名称为{model}")
            completion = openAILLMService.llm_model_client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system_prompts}],
                temperature=0.3,
                max_tokens=4096,
                stream=False,
            )
            answer = completion.choices[0].message.content
            index = completion.choices[0].message.content.find("</think>")  # 推理模型过滤思考内容
            if index != -1:
                answer = answer[index + len("</think>") :]
            # 去除空格和换行符
            answer = answer.strip()
            answer = answer.split("？")[0] + "？" if len(answer) > 50 else answer
            return answer
        except Exception as e:
            raise

    @staticmethod
    async def get_upload_file_v1(file_obj, file_name):
        """
        上传文件并返回 MinIO 文件路径
        """
        try:
            # 直接读取上传的文件内容
            content = await file_obj.read()

            # 构造 MinIO 路径
            date = datetime.datetime.now().strftime("%Y_%m_%d")
            folder = generate_unique_id("Temp", datacenter_id=1, worker_id=1)
            remote_path = f"{date}/{folder}/{file_name}"
            bucket_name = "tiance-base-temp-file-bucket"

            # 上传文件到 MinIO
            file_stream = BytesIO(content)
            await run_in_threadpool(MinIoUtil.upload_file_stream, bucket_name, remote_path, file_stream, len(content))

            return remote_path

        except Exception as e:
            raise

    # @staticmethod
    # async def embedding_document(
    #     doc: str,
    #     file_name: str,
    #     chunk_method: str = None,
    #     chunk_size: int = 500,
    #     chunk_overlap: int = 50,
    #     separator: list = ["/n"],
    #     file_id: str = None,
    # ):
    #     try:
    #         ###切片方法
    #         set_progress(file_id, "1", 0.0, time.time())
    #         if file_name.endswith(".csv"):
    #             chunks = [i.page_content for i in doc]
    #             set_progress(file_id, "1", 100.0, time.time())
    #         else:
    #             docs = doc
    #             if file_name.endswith(".txt") and not isinstance(docs, str):
    #                 docs = doc[0].page_content
    #             if chunk_method == "RecursiveCharacterTextSplitter":
    #                 textsplitter = RecursiveCharacterTextSplitter(
    #                     chunk_size=chunk_size,
    #                     chunk_overlap=chunk_overlap,
    #                     separators=separator if isinstance(separator, list) else ["\n"],
    #                     length_function=len,
    #                 )
    #                 chunks = textsplitter.split_text(docs)
    #             elif chunk_method == "SpacyTextSplitter":
    #                 textsplitter = SpacyTextSplitter(
    #                     chunk_size=chunk_size,
    #                     chunk_overlap=chunk_overlap,
    #                     separator=separator[0] if isinstance(separator, list) else "\n",
    #                     pipeline="zh_core_web_sm",
    #                 )
    #                 chunks = textsplitter.split_text(docs)
    #             elif chunk_method == "CharacterTextSplitter":
    #                 textsplitter = CharacterTextSplitter(
    #                     separator=separator[0] if isinstance(separator, list) else "\n",
    #                     chunk_size=chunk_size,
    #                     chunk_overlap=chunk_overlap,
    #                 )
    #                 chunks = textsplitter.split_text(docs)
    #             else:
    #                 raise Exception("切片方法不在候选范围中")
    #             logger.info(f"分块数量 {len(chunks)}")
    #             set_progress(file_id, "1", 100.0, time.time())
    #         return chunks
    #
    #     except Exception as e:
    #         raise

    @staticmethod
    async def repeat_file_detect(knowledge_id, upload_name_list):
        """
        检测上传文件名称中是否与已上传文件存在重复
        :return:
        重名文件名称列表
        """
        try:
            # 先获取所有已上传文件的文件名称
            file_list = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                search_condition={"knowledge_id": knowledge_id},
            )

            file_name_list = [file["file_name"] for file in file_list]
            repeat_name_list = list(set(upload_name_list) & set(file_name_list))

            return repeat_name_list

        except (Exception, RuntimeError) as e:
            raise

    @staticmethod
    async def insert_file_info(knowledge_id, file_name, is_save_image=""):
        try:
            # 雪花算法生成唯一标识id
            await asyncio.sleep(0.1)
            _id = generate_unique_id("F", datacenter_id=1, worker_id=1)
            retry_num = 5
            for retry in range(retry_num):
                if MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, _id):
                    logger.info(f"检测到重复文件id{_id}，正在重新生成文件id")
                    _id = generate_unique_id("F", datacenter_id=1, worker_id=1)
                    if retry == retry_num - 1:
                        return False, ""
                else:
                    break
            # 获取当前时间
            create_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # 信息入库
            MongodbUtil.insert_one(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                {
                    "_id": _id,
                    "knowledge_id": knowledge_id,
                    "file_name": file_name,
                    "status": 1,
                    "info": "",
                    "create_time": create_time,
                    "is_save_image": is_save_image,
                },
            )
            return True, _id  # 返回成功标志
        except Exception as e:
            raise

    @staticmethod
    async def add_embedding_document(
        knowledge_id: str,
        chunks: list,
        file_name: str,
        file_id: str = "",
    ):
        try:
            # 获取嵌入模型和稀疏向量支持信息
            query_result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.KB_COLLECTION, search_condition={"_id": ObjectId(knowledge_id)}
            )
            assert query_result is not None, "嵌入模型配置错误！"
            for i in query_result:
                embedding_id = i.get("embedding_id")
                model_data = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(embedding_id),
                )
                if model_data:
                    embedding_model = model_data.get("model_uid", "")
                # 从MongoDB读取稀疏向量支持信息，默认为False
                supports_sparse = i.get("supports_sparse_vector", False)

            embeddingUtil = EmbeddingUtil(embedding_id=embedding_id)
            logger.info(f"从知识库配置读取稀疏向量支持状态: {supports_sparse}")

            data = []
            parent_data = []  # 存储卷积为parent的数据
            upload_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            progress_step = 100.0 / len(chunks)
            set_progress(file_id, "2", 0.0, time.time())

            for i in range(len(chunks)):
                # 检查是否为parent类型的chunk
                if hasattr(chunks[i].metadata, "chunk_split_type") and chunks[i].metadata.chunk_split_type == "parent":
                    # 对于parent类型的chunk，直接存储到MongoDB，不进行向量嵌入
                    question = await Knowledge_File_service.generate_question_answer(chunks[i].content)
                    question = question.replace("\n", " ")
                    question = question.replace("\\n", " ")

                    parent_chunk_data = {
                        "file_name": file_name,
                        "file_id": file_id,
                        "file_time": upload_time,
                        "number": chunks[i].metadata.chunk_index,
                        "content": chunks[i].content,
                        "ori_content": chunks[i].ori_content,
                        "question": question,
                        "source_data": chunks[i].metadata.source_data if chunks[i].metadata.source_data else [],
                        "chunk_split_type": chunks[i].metadata.chunk_split_type,
                        "parent_node": chunks[i].metadata.parent_node,
                        "chunk_id": chunks[i].metadata.chunk_id,
                        "knowledge_id": knowledge_id,
                        "status": 1,
                    }
                    parent_data.append(parent_chunk_data)
                    # logger.info(f"Parent类型chunk直接存储到MongoDB，内容：{chunks[i].content[:100]}...")
                else:
                    # 对于非parent类型的chunk，进行向量嵌入
                    question = await Knowledge_File_service.generate_question_answer(chunks[i].content)
                    question = question.replace("\n", " ")
                    question = question.replace("\\n", " ")
                    question_answer = json.dumps({"QUESTION": question, "ANSWER": chunks[i].content})

                    # 生成稠密向量
                    question_answer_vector = embeddingUtil.get_embedding(
                        model_uid=embedding_model, input=question_answer
                    )

                    # 构建基础数据字典
                    chunk_data = {
                        "file_name": file_name,
                        "file_id": file_id,
                        "file_time": upload_time,
                        "number": chunks[i].metadata.chunk_index,
                        "content": chunks[i].content,
                        "ori_content": chunks[i].ori_content,
                        "dense_vector": question_answer_vector[0],
                        "question": question,
                        "source_data": chunks[i].metadata.source_data if chunks[i].metadata.source_data else [],
                        "chunk_split_type": chunks[i].metadata.chunk_split_type,
                        "parent_node": chunks[i].metadata.parent_node,
                        "chunk_id": chunks[i].metadata.chunk_id,
                    }

                    # 如果模型支持稀疏向量，添加稀疏向量字段
                    if supports_sparse:
                        try:
                            sparse_vector = embeddingUtil.get_embedding(
                                model_uid=embedding_model, input=question_answer, return_sparse=True
                            )
                            if sparse_vector and len(sparse_vector) > 0:
                                sparse_result = sparse_vector[0] if isinstance(sparse_vector, list) else sparse_vector
                                chunk_data["sparse_model"] = sparse_result
                                logger.debug(f"为第{i + 1}个chunk添加了稀疏向量")
                        except Exception as e:
                            logger.warning(f"生成第{i + 1}个chunk的稀疏向量失败: {str(e)}")

                    data.append(chunk_data)
                    logger.info(f"生成的问题为：{question}")

                set_progress(file_id, "2", progress_step * (i + 1), time.time())

            set_progress(file_id, "2", 100.0, time.time())
            set_progress(file_id, "3", 0.0, time.time())

            # 将parent类型的数据批量存储到MongoDB
            if parent_data:
                MongodbUtil.insert_many(CollectionConfig.CHUNK_COLLECTION, parent_data)
                # logger.info(f"成功将{len(parent_data)}个parent类型chunk批量存储到MongoDB")

            # 将需要向量化的数据存储到Milvus
            if data:
                milvus = MilvusUtil()
                collection_name = "_" + knowledge_id
                batch_size = 500  # 每批次插入的数据量
                for i in range(0, len(data), batch_size):
                    batch_data = data[i : i + batch_size]
                    await milvus.add_document(collection_name=collection_name, data=batch_data)
                    if len(data) > 0 and i > 0:
                        set_progress(file_id, "3", i / len(data), time.time())

            set_progress(file_id, "3", 100.0, time.time())
            logger.info("知识库添加文件成功")
            return True
        except (Exception, RuntimeError) as e:
            raise


    @staticmethod
    async def add_embedding_document_without_question(
        knowledge_id: str,
        chunks: list,
        file_name: str,
        file_id: str = "",
    ):
        try:
            # 获取嵌入模型和稀疏向量支持信息
            query_result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.KB_COLLECTION, search_condition={"_id": ObjectId(knowledge_id)}
            )
            assert query_result is not None, "嵌入模型配置错误！"
            for i in query_result:
                embedding_id = i["embedding_id"]
                model_data = MongodbUtil.query_doc_by_id(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    doc_id=ObjectId(embedding_id),
                )
                if model_data:
                    embedding_model = model_data.get("model_uid", "")
                # 从MongoDB读取稀疏向量支持信息，默认为False
                supports_sparse = i.get("supports_sparse_vector", False)
                # maxtoken=i.get('max_tokens',"")

            embeddingUtil = EmbeddingUtil(embedding_id=embedding_id)
            logger.info(f"从知识库配置读取稀疏向量支持状态: {supports_sparse}")

            data = []
            parent_data = []  # 存储卷积为parent的数据
            upload_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if len(chunks) >= 1:
                progress_step = 100.0 / len(chunks)
            else:
                progress_step = 100.0
            set_progress(file_id, "2", 0.0, time.time())

            # 分离parent类型和非parent类型的chunks
            parent_chunks = []
            non_parent_chunks = []

            for chunk in chunks:
                if hasattr(chunk.metadata, "chunk_split_type") and chunk.metadata.chunk_split_type == "parent":
                    parent_chunks.append(chunk)
                else:
                    non_parent_chunks.append(chunk)

            # 处理parent类型的chunks，直接存储到MongoDB
            for chunk in parent_chunks:
                parent_chunk_data = {
                    "file_name": file_name,
                    "file_id": file_id,
                    "file_time": upload_time,
                    "number": chunk.metadata.chunk_index,
                    "content": chunk.content,
                    "ori_content": chunk.ori_content,
                    "question": "",  # 不生成问答对
                    "source_data": chunk.metadata.source_data if chunk.metadata.source_data else [],
                    "chunk_split_type": chunk.metadata.chunk_split_type,
                    "parent_node": chunk.metadata.parent_node,
                    "chunk_id": chunk.metadata.chunk_id,
                    "knowledge_id": knowledge_id,
                    "status": 1,
                }
                parent_data.append(parent_chunk_data)
                # logger.info(f"Parent类型chunk直接存储到MongoDB，内容：{chunk.content[:100]}...")

            # 处理非parent类型的chunks，进行向量嵌入
            if non_parent_chunks:
                batch_size = ApiConfig.Batch_Size
                j = 0
                for i in range(0, len(non_parent_chunks), batch_size):
                    batch_data = non_parent_chunks[i : i + batch_size]
                    texts = [ch.content for ch in batch_data]

                    # 批量生成稠密向量
                    embeddings_i = embeddingUtil.get_embedding(model_uid=embedding_model, input=texts)

                    # 如果支持稀疏向量，批量生成稀疏向量
                    sparse_embeddings_i = []
                    if supports_sparse:
                        try:
                            sparse_results = embeddingUtil.get_embedding(
                                model_uid=embedding_model, input=texts, return_sparse=True
                            )
                            if sparse_results and len(sparse_results) > 0:
                                sparse_embeddings_i = sparse_results
                        except Exception as e:
                            logger.warning(f"批量生成稀疏向量失败: {str(e)}")
                            sparse_embeddings_i = []

                    for index in range(len(batch_data)):
                        # 构建基础数据字典
                        chunk_data = {
                            "file_name": file_name,
                            "file_id": file_id,
                            "file_time": upload_time,
                            "number": batch_data[index].metadata.chunk_index,
                            "content": batch_data[index].content,
                            "ori_content": batch_data[index].ori_content,
                            "dense_vector": embeddings_i[index],
                            "source_data": batch_data[index].metadata.source_data,
                            "chunk_split_type": batch_data[index].metadata.chunk_split_type,
                            "parent_node": batch_data[index].metadata.parent_node,
                            "chunk_id": batch_data[index].metadata.chunk_id,
                        }

                        # 如果有稀疏向量，添加到数据中
                        if supports_sparse and index < len(sparse_embeddings_i):
                            chunk_data["sparse_model"] = sparse_embeddings_i[index]

                        data.append(chunk_data)
                    j += 1
                    set_progress(file_id, "2", progress_step * len(non_parent_chunks[i : i + batch_size]), time.time())

            set_progress(file_id, "2", 100.0, time.time())
            set_progress(file_id, "3", 0.0, time.time())

            # 将parent类型的数据批量存储到MongoDB
            if parent_data:
                MongodbUtil.insert_many(CollectionConfig.CHUNK_COLLECTION, parent_data)
                logger.info(f"成功将{len(parent_data)}个parent类型chunk批量存储到MongoDB")

            # 将需要向量化的数据存储到Milvus
            if data:
                milvus = MilvusUtil()
                collection_name = "_" + knowledge_id
                batch_size = 500  # 每批次插入的数据量
                for i in range(0, len(data), batch_size):
                    batch_data = data[i : i + batch_size]
                    await milvus.add_document(collection_name=collection_name, data=batch_data)
                    if len(data) > 0 and i > 0:
                        set_progress(file_id, "3", i / len(data), time.time())

            set_progress(file_id, "3", 100.0, time.time())
            logger.info(f"知识库添加文件{file_name}成功")
            return True, ""
        except (Exception, RuntimeError) as e:
            raise

    @staticmethod
    async def _get_file_ids_by_knowledge_id(knowledge_id):
        """获取知识库中所有文件的ID列表"""
        file_list = MongodbUtil.query_docs_by_condition(
            collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
            search_condition={"knowledge_id": knowledge_id, "status": 0},
        )
        return [file["_id"] for file in file_list if file.get("_id", "") != ""]

    @staticmethod
    async def _process_reference_node(knowledge_id, source_data):
        """处理引用节点数据，提取图片和表格引用信息"""
        reference_node = []
        if not source_data:
            return reference_node

        f_ids = await Knowledge_File_service._get_file_ids_by_knowledge_id(knowledge_id)

        for item in source_data:
            # 处理图片引用
            src_ref_images = item.get("src_ref_image", [])
            if src_ref_images and src_ref_images != True and src_ref_images != False:
                for src_ref_image in src_ref_images:
                    image_node = src_ref_image
                    for f_id in f_ids:
                        file = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_id=f_id
                        )
                        if file.get("parse_result", ""):
                            for i in file["parse_result"]["result"]:
                                if image_node and i["id"] == image_node:
                                    reference_node.append(
                                        {
                                            "img_path": i["img_path"],
                                            "type": i["type"],
                                            "text": i.get("text",""),
                                            "bbox": i["bbox"],
                                            "page_idx": i["page_idx"],
                                            "image_footnote": i.get("image_footnote", [""]),
                                            "caption": i["caption"],
                                            "id": image_node,
                                        }
                                    )
                                    break

            # 处理表格引用
            src_ref_tables = item.get("src_ref_table", [])
            if src_ref_tables and src_ref_tables != True and src_ref_tables != False:
                for src_ref_table in src_ref_tables:
                    table_node = src_ref_table
                    for f_id in f_ids:
                        file = MongodbUtil.query_doc_by_id(
                            collection_name=CollectionConfig.FILE_PARSE_RESULT, doc_id=f_id
                        )
                        if file.get("parse_result", ""):
                            for i in file["parse_result"]["result"]:
                                if table_node and i["id"] == table_node:
                                    reference_node.append(
                                        {
                                            "img_path": i["img_path"],
                                            "type": i["type"],
                                            "text": i.get("text",""),
                                            "bbox": i["bbox"],
                                            "page_idx": i["page_idx"],
                                            "table_footnote": i.get("table_footnote", [""]),
                                            "caption": i["caption"],
                                        }
                                    )
                                    break

        return reference_node

    @staticmethod
    async def _build_chunk_result(result, reference_node, child_chunk=None):
        """构建切片结果对象"""
        # if child_chunk==None:
        return {
            "index": str(result.get("index", "")),
            "number": result["number"],
            "file_name": result["file_name"],
            "chunk_content": result["content"],
            "size": len(result["content"]),
            "question": result.get("question", ""),
            "is_generate": True if result.get("question", None) else False,
            "reference_node": reference_node,
            "child_chunk": child_chunk or [],
        }

    @staticmethod
    async def chunk_result_query_v2(knowledge_id, file_id, page, page_size, filter_condition=None):
        try:
            # 获取分块方法
            chunk_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_ARRANGE_INFO, ObjectId(knowledge_id))
            chunk_method = chunk_result.get("chunk_method", "") if chunk_result else "old_method"

            # 判断是否为传统方法
            is_traditional_method = chunk_method in [
                "CharacterTextSplitter",
                "RecursiveCharacterTextSplitter",
                "SpacySplitter",
                "old_method",
            ]

            punctuation_pattern = re.compile(r"[\W_]+", re.UNICODE)

            def normalize_text(text: Optional[str]) -> str:
                return punctuation_pattern.sub("", text or "")

            filter_text_raw = filter_condition.strip() if filter_condition else None
            normalized_filter = normalize_text(filter_text_raw)
            compiled_filter = (
                re.compile(re.escape(normalized_filter), re.IGNORECASE) if normalized_filter else None
            )

            enable_true_pagination = False

            # 构建查询条件
            conditions = []
            if len(file_id) > 0:
                conditions.append(f"file_id in {file_id}")

            if is_traditional_method:
                conditions.extend(["chunk_split_type != 'parent'", "chunk_split_type != 'child'"])
            else:
                conditions.append("chunk_split_type == 'parent'")

            condition = " and ".join(conditions)

            # 查询数据 - 根据方法类型选择数据源
            if is_traditional_method:
                milvus = MilvusUtil("default")
                if enable_true_pagination:
                    results, total_len = await milvus.query_by_condition_pagination(
                        collection_name="_" + str(knowledge_id),
                        search_condition=condition,
                        page=page,
                        page_size=page_size,
                        sort_field=["file_name", "number"],
                        reverse=False,
                        content_filter=normalized_filter,
                    )
                else:
                    all_results, _ = await milvus.query_by_condition_pagination(
                        collection_name="_" + str(knowledge_id),
                        search_condition=condition,
                        page=1,
                        page_size=0,
                        sort_field=["file_name", "number"],
                        reverse=False,
                        content_filter=normalized_filter,
                    )
                    total_len = len(all_results)
                    start_index = (page - 1) * page_size
                    end_index = start_index + page_size
                    buckets = defaultdict(list)
                    for item in all_results:
                        buckets[item['file_name']].append(item)

                    ordered = []
                    for fname in sorted(buckets):  # 文件名统一顺序
                        ordered.extend(sorted(buckets[fname], key=lambda x: x['number']))
                    results = ordered[start_index:end_index]
            else:
                # 父级方法：从MongoDB查询parent类型数据
                mongo_conditions = {}
                if len(file_id) > 0:
                    mongo_conditions["file_id"] = {"$in": file_id}
                mongo_conditions["knowledge_id"] = knowledge_id

                if enable_true_pagination and normalized_filter:
                    regex_body = r"[\W_]*".join(list(normalized_filter))
                    mongo_regex_pattern = f".*{regex_body}.*"
                    mongo_regex = re.compile(mongo_regex_pattern, re.IGNORECASE)
                    mongo_conditions["$or"] = [
                        {"content": mongo_regex},
                        {"chunk_content": mongo_regex},
                    ]

                if enable_true_pagination:
                    cursor = MongodbUtil.query_docs_by_condition_pagination(
                        collection_name=CollectionConfig.CHUNK_COLLECTION,
                        search_condition=mongo_conditions,
                        page=page,
                        page_size=page_size,
                        sort_field=["file_name", "number"],
                        reverse=False,
                    )

                    results = list(cursor)
                    total_len = MongodbUtil.count_documents_by_condition(
                        CollectionConfig.CHUNK_COLLECTION, mongo_conditions
                    )
                else:
                    all_parent_results = MongodbUtil.query_docs_by_condition(
                        collection_name=CollectionConfig.CHUNK_COLLECTION, search_condition=mongo_conditions
                    )

                    sorted_results = sorted(all_parent_results, key=lambda x: (x.get("file_name", ""), x.get("number", 0)))

                    if compiled_filter:
                        sorted_results = [
                            item
                            for item in sorted_results
                            if compiled_filter.search(
                                normalize_text(str(item.get("content") or item.get("chunk_content") or ""))
                            )
                        ]

                    total_len = len(sorted_results)
                    start_index = (page - 1) * page_size
                    end_index = start_index + page_size
                    results = sorted_results[start_index:end_index]

            total_result = []

            # 如果是父级方法，先收集所有需要查询的子节点，然后批量查询
            all_child_nodes = set()
            parent_results_mapping = {}  # 存储每个父级结果对应的子节点列表

            if not is_traditional_method:
                for result in results:
                    parent_nodes = result.get("parent_node", [])
                    if parent_nodes:
                        all_child_nodes.update(parent_nodes)
                        parent_results_mapping[result["chunk_id"]] = parent_nodes

                # 批量查询所有子节点 - 子节点仍然从Milvus查询
                child_results_by_id = {}
                if all_child_nodes:
                    child_conditions = f"chunk_id in {list(all_child_nodes)}"
                    milvus = MilvusUtil("default")
                    child_results, child_total_len = await milvus.query_by_condition_pagination(
                        collection_name="_" + str(knowledge_id),
                        search_condition=child_conditions,
                        page=1,
                        page_size=len(all_child_nodes) * 10,  # 确保能获取到所有子节点
                        sort_field=["file_name", "number"],
                        reverse=False,
                    )

                    # 按 chunk_id 分组子节点结果
                    for child_result in child_results:
                        chunk_id = child_result.get("chunk_id")
                        if chunk_id not in child_results_by_id:
                            child_results_by_id[chunk_id] = []
                        child_results_by_id[chunk_id].append(child_result)

            for result in results:
                # 处理引用节点
                reference_node = await Knowledge_File_service._process_reference_node(
                    knowledge_id, result.get("source_data", [])
                )

                if is_traditional_method:
                    # 传统方法：直接构建结果
                    chunk_result = await Knowledge_File_service._build_chunk_result(result, reference_node)
                    total_result.append(chunk_result)
                else:
                    # 父级方法：从预查询的结果中获取子切片
                    result["index"] = result["chunk_id"]
                    parent_nodes = parent_results_mapping.get(result["chunk_id"], [])
                    child_chunk = []

                    # 按原始 parent_nodes 顺序构建子切片
                    for parent_node in parent_nodes:
                        if parent_node in child_results_by_id:
                            # 取第一个匹配的子节点（保持原有逻辑）
                            child_result = child_results_by_id[parent_node][0]
                            child_chunk.append(await Knowledge_File_service._build_chunk_result(child_result, []))

                    chunk_result = await Knowledge_File_service._build_chunk_result(result, reference_node, child_chunk)
                    total_result.append(chunk_result)

            method_type = "tradition" if is_traditional_method else "parent"
            return total_result, total_len, method_type

        except Exception as e:
            raise

    #
    # @staticmethod
    # async def is_task_active(task_id: str):
    #     inspect = celery_app.control.inspect()
    #
    #     # 正在运行的任务
    #     active = inspect.active() or {}
    #     for worker, tasks in active.items():
    #         for task in tasks:
    #             if task.get("id") == task_id:
    #                 return 0
    #
    #     # 已经被 worker 预取但没开始跑
    #     reserved = inspect.reserved() or {}
    #     for worker, tasks in reserved.items():
    #         for task in tasks:
    #             if task.get("id") == task_id:
    #                 return 1
    #
    #     # 等待调度的任务（定时/延迟）
    #     scheduled = inspect.scheduled() or {}
    #     for worker, tasks in scheduled.items():
    #         for task in tasks:
    #             if task.get("request", {}).get("id") == task_id:
    #                 return 2
    #
    #     return 3

    @staticmethod
    async def delete_file(file_id, knowledge_id, file_name):
        try:
            for task_id in [f"{file_id}:parse"]:
                result = AsyncResult(task_id, app=celery_app)

                if result.state == "PENDING":
                    # 任务在队列里，还没执行，直接 revoke
                    result.revoke()
                    logger.info(f"任务 {task_id} 取消成功.")

                elif result.state in ("RECEIVED", "STARTED"):
                    # 任务已被 worker 接收/正在执行，需要 terminate
                    result.revoke(terminate=True, signal="SIGTERM")
                    logger.info(f"任务 {task_id} 取消成功 (正在进行).")

                elif result.state in ("SUCCESS", "FAILURE", "REVOKED"):
                    # 任务已经完成/失败/被取消，不需要操作
                    logger.info(f"任务 {task_id} 已完成，当前状态: {result.state}")

                else:
                    # 其他未知状态
                    logger.info(f"任务 {task_id} 处于未知状态: {result.state}")
            # 正确地使用变量引用
            condition = f"file_name == '{file_name}'"
            # 执行删除操作
            milvus = MilvusUtil()
            collection_name = "_" + str(knowledge_id)
            await milvus.del_document(collection_name=collection_name, del_conditions=condition)
            MinIoUtil.remove_file(bucket_name="tiance-base", file_name=file_name, file_path=f"{knowledge_id}")
            MongodbUtil.del_docs_by_condition(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, del_condition={"_id": file_id}
            )
            return True  # 返回成功标志
        except Exception as e:
            raise

    @staticmethod
    async def file_query_page(knowledge_id, file_name, page, page_size):
        try:
            # 执行查找操作
            search_condition = {
                "knowledge_id": knowledge_id,
                "file_name": {"$regex": f"{re.escape(file_name)}(\\_.*)?", "$options": "i"},
            }

            # results = MongodbUtil.query_docs_by_condition(
            #     collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, search_condition=search_condition
            # )
            def parse_upload_time(upload_time_str):
                return datetime.datetime.strptime(upload_time_str, "%Y-%m-%d %H:%M:%S")

            results = MongodbUtil.query_docs_by_condition_pagination(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                search_condition=search_condition,
                page=page,
                page_size=page_size,
                sort_field="create_time",
                reverse=True,
            )

            len_results = MongodbUtil.count_documents_by_condition(
                CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, search_condition
            )
            unique_files = []
            for result in results:
                file_name = result["file_name"]
                upload_time = result["create_time"]
                status = result["status"] if result.get("status", None) else 0
                info = result["info"] if result.get("info", None) else ""
                remote_path = result.get("remote_path", "")
                convert_path = result.get("convert_path", "")
                layout_path = result.get("layout_path", "")
                is_save_image = result.get("is_save_image", "")
                remove_image_path = result.get("remove_image_path", "")
                unique_files.append(
                    {
                        "file_name": file_name,
                        "upload_time": upload_time,
                        "file_id": result["_id"],
                        # "parse_result": result.get("parse_result", {}),
                        "status": status,
                        "info": info,
                        "remote_path": remote_path,
                        "convert_path": convert_path,
                        "layout_path": layout_path,
                        "is_save_image": is_save_image,
                        "remove_image_path": remove_image_path,
                    }
                )
            # 记录更详细的日志信息
            return unique_files, len_results  # 返回成功标志
        except Exception as e:
            raise

    @staticmethod
    async def file_query_all(knowledge_id, file_name):
        try:
            # 执行查找操作
            search_condition = {
                "knowledge_id": knowledge_id,
                "file_name": {"$regex": f"{re.escape(file_name)}(\\_.*)?", "$options": "i"},
                "$or": [{"status": 0}, {"status": {"$exists": False}}],
            }
            results = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, search_condition=search_condition
            )
            unique_files = []
            for result in results:
                file_name = result["file_name"]
                upload_time = result["create_time"]
                if file_name not in [item["file_name"] for item in unique_files]:
                    status = result["status"] if result.get("status", None) else 0
                    unique_files.append(
                        {"file_name": file_name, "upload_time": upload_time, "file_id": result["_id"], "status": status}
                    )
            logger.info(f"查询到文件数量 {len(unique_files)}")
            # 记录更详细的日志信息
            return unique_files  # 返回成功标志
        except Exception as e:
            raise

    @staticmethod
    async def update_chunk_by_child(index, new_content, new_question, knowledge_id):
        try:
            milvus = MilvusUtil()
            condition = f"index == {index}"
            collection_name = "_" + str(knowledge_id)
            result = await milvus.query_by_scalar(collection_name=collection_name, query_conditions=condition)

            # 获取嵌入模型
            query_result = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.KB_COLLECTION, search_condition={"_id": ObjectId(knowledge_id)}
            )
            if query_result:
                for i in query_result:
                    embedding_id = i["embedding_id"]
                    model_data = MongodbUtil.query_doc_by_id(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                        doc_id=ObjectId(embedding_id),
                    )
                    if model_data:
                        embedding_model = model_data.get("model_uid", "")
            else:
                logger.info("嵌入模型配置错误！")
                return False

            embeddingUtil = EmbeddingUtil(embedding_id=embedding_id)
            embedding = embeddingUtil.get_embedding(model_uid=embedding_model, input=[new_content])

            data = [result[0]]

            if new_question:
                data[0]["question"] = new_question
                data[0]["content"] = result[0]["content"]

            if new_content:
                data[0]["content"] = new_content
                embedding = embedding[0]
                data[0]["dense_vector"] = embedding

            if result[0].get("source_data", None):
                data[0]["source_data"] = result[0]["source_data"]

            result = await milvus.update_document(collection_name=collection_name, data=data)
            return result  # 返回成功标志
        except Exception as e:
            raise

    @staticmethod
    async def update_chunk_by_parent(new_content, new_question, chunk_id):
        try:
            update_condition = {}

            if new_question:
                update_condition["question"] = new_question

            if new_content:
                update_condition["content"] = new_content

            result = MongodbUtil.update_docs_by_condition(
                CollectionConfig.CHUNK_COLLECTION,
                {"chunk_id": chunk_id},
                replace_data={"$set": update_condition},
            )
            return result  # 返回成功标志
        except Exception as e:
            raise

    @staticmethod
    async def upload_and_extract_archive(file_obj, knowledge_id):
        """
        上传压缩包并解压文件
        :param file_obj: 前端传入的压缩包文件对象
        :param account_id: 用户ID
        :return: 上传结果
        """
        try:
            file_name = file_obj.filename
            upload_path = Path(__file__).parents[2] / "upload"
            local_path = f"{upload_path}/{knowledge_id}$$${file_name}"
            unique_id = generate_unique_id("_", datacenter_id=1, worker_id=1)
            extracted_dir = f"{upload_path}/compress/{unique_id}"

            # 异步保存上传文件
            async with aiofiles.open(local_path, "wb") as temp_file:
                content = await file_obj.read()
                await temp_file.write(content)

            file_extension = file_obj.filename.split(".")[-1].lower()

            # 解压处理
            if file_extension == "zip":
                with zipfile.ZipFile(local_path, "r") as zip_ref:
                    for file_info in zip_ref.infolist():
                        # 解码文件名
                        decoded_filename = decode_filename(file_info.filename)
                        file_info.filename = decoded_filename

                        # 提取文件
                        zip_ref.extract(file_info, extracted_dir)
            elif file_extension == "rar":
                import rarfile

                path = Path(__file__).parents[2] / "UnRAR"
                rarfile.UNRAR_TOOL = path
                # rarfile.UNRAR_TOOL = "/usr/bin/unar"  # 服务器专用
                with rarfile.RarFile(local_path, "r") as rar_ref:
                    rar_ref.extractall(extracted_dir)

            elif file_extension == "7z":
                with py7zr.SevenZipFile(local_path, "r") as z:
                    z.extractall(extracted_dir)

            else:
                return {"message": "不支持的压缩格式", "status": False}

            if Path(local_path).exists():
                Path(local_path).unlink()  # 删除临时压缩包

            extracted_files = list(Path(extracted_dir).rglob("*"))
            return {
                "message": "解压成功",
                "files": [str(file) for file in extracted_files],
                "status": True,
                "extracted_dir": extracted_dir,
            }

        except Exception as e:
            raise

    @staticmethod
    async def similar_file_detect(knowledge_id, upload_name_list, repeat_file_list):
        """
        检测上传文件名称中是否与已上传文件存在重复
        :return:
        重名文件名称列表
        """
        try:
            similar_name_list = []

            def find_similar_files(file_list, file_name, similarity_threshold=0.85):
                try:
                    if len(file_list) == 0:
                        similar_files = []
                        return similar_files

                    MongodbUtil.connect()
                    # 根据知识库的名称获取到embedding模型名称
                    query_result = MongodbUtil.query_docs_by_condition(
                        collection_name=CollectionConfig.KB_COLLECTION, search_condition={"_id": ObjectId(knowledge_id)}
                    )
                    embedding_model = ModelConfig.DEFAULT_EMBEDDING_MODEL
                    for item in query_result:
                        if item:
                            embedding_id = item["embedding_id"]
                            model_data = MongodbUtil.query_doc_by_id(
                                collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                                doc_id=ObjectId(embedding_id),
                            )
                            if model_data:
                                embedding_model = model_data.get("model_uid", "")
                            rerank_id = item["rerank_id"]
                        else:
                            logger.info("知识库不存在！！")
                            raise ValueError("知识库不存在")
                    # 获取向量embedding工具
                    embeddingUtil = EmbeddingUtil(embedding_id=embedding_id)
                    logger.info(f"嵌入模型为:{embedding_model}")

                    file_name_embedding = embeddingUtil.get_embedding(model_uid=embedding_model, input=file_name)
                    file_list_embedding = []
                    for i in range(len(file_list)):
                        file_list_embedding.append(
                            embeddingUtil.get_embedding(model_uid=embedding_model, input=file_list[i])
                        )

                    import numpy as np

                    similar_files = []
                    file_name_vector = np.array(file_name_embedding[0])  # 将 file_name_embedding 转换为向量

                    for i, file_embedding in enumerate(file_list_embedding):
                        file_vector = np.array(file_embedding[0])  # 将文件嵌入转换为向量
                        # 计算点积
                        dot_product = np.dot(file_vector, file_name_vector)
                        # 计算模长
                        norm_file = np.linalg.norm(file_vector)
                        norm_name = np.linalg.norm(file_name_vector)
                        # 计算余弦相似度
                        cosine_similarity = dot_product / (norm_file * norm_name)
                        # 筛选相似度大于阈值的文件名
                        if cosine_similarity >= similarity_threshold:
                            _id = MongodbUtil.query_docs_by_condition(
                                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                                search_condition={"knowledge_id": knowledge_id, "file_name": file_list[i]},
                            )[0]["_id"]
                            similar_files.append(
                                {"filename": file_list[i], "id": _id, "url": f"{knowledge_id}/{file_list[i]}"}
                            )
                    return similar_files
                except Exception as e:
                    raise

                # similar_files = []
                # for existing_file in file_list:
                #     # 计算两个文件名的相似度
                #     similarity = difflib.SequenceMatcher(None, existing_file, file_name).ratio()
                #     # 如果相似度大于阈值，加入结果列表
                #     if similarity >= similarity_threshold and existing_file != file_name and file_name not in repeat_file_list:
                #         _id = MongodbUtil.query_docs_by_condition(
                #             collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                #             search_condition={"kb_name": kb_name, "account_id": account_id, "file_name": existing_file}
                #         )[0]["_id"]
                #         similar_files.append({"filename": existing_file, "id": _id, "url": f"{account_id}/{kb_name}/{existing_file}"})
                # return similar_files

            # 先获取所有已上传文件的文件名称
            file_list = MongodbUtil.query_docs_by_condition(
                collection_name=CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                search_condition={"knowledge_id": knowledge_id, "status": 0},
            )
            file_name_list = [file["file_name"] for file in file_list]
            for file_name in upload_name_list:
                similar_files = find_similar_files(file_name_list, file_name, similarity_threshold=0.85)
                if similar_files:
                    similar_name_list.append({"filename": file_name, "files": similar_files})

            return similar_name_list

        except (Exception, RuntimeError) as e:
            raise

    @staticmethod
    async def is_own_knowledge(knowledge_id, account_id, db):
        try:
            knowledge_info = MongodbUtil.query_doc_by_id(
                collection_name=CollectionConfig.KB_COLLECTION, doc_id=ObjectId(knowledge_id)
            )
            team_code = knowledge_info.get("team_code", "")
            if team_code:  # 团队知识库
                teams = UsrAuthService.usr_team(db=db, auth=UsrEntity(account_id=account_id))
                teams = [team["team_code"] for team in teams]
                if team_code in teams:
                    return True
                else:
                    return False

            else:  # 个人知识库
                if knowledge_info["account_id"] == account_id:
                    return True
                else:
                    return False

        except Exception as e:
            raise
