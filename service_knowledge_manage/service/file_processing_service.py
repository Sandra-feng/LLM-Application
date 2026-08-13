#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：file_processing_service.py
@Author  ：zhou_min
@Date    ：2025/08/19
@Description: 文件处理服务 - 重构后统一的文件上传、解析、入库逻辑
"""

import asyncio
import os
import time
from pathlib import Path
from typing import Any, Optional

from bson import ObjectId
from fastapi import BackgroundTasks, Request
from fastapi.concurrency import run_in_threadpool
from loguru import logger

from base_configs.api_config import ApiConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.minio_util import MinIoUtil
from base_utils.mongodb_util import MongodbUtil
from service_celery_manage.tasks import file_parse_task, split_embedding_task
from service_knowledge_manage.service.knowledge_file_service import Knowledge_File_service
from service_knowledge_manage.service.parse_service import FileParseService
from service_knowledge_manage.service.splitter_service import SplitterService
from service_knowledge_manage.service.util.file_progress import set_progress

# logger = loguru logger (auto-migrated)
class FileProcessingService:
    """文件处理服务 - 统一处理文件上传、解析、入库流程"""

    def __init__(self):
        self.file_parser = FileParseService()
        self.splitter_service = SplitterService()
        self.upload_path = Path(__file__).parents[2] / "upload"

    async def preview_file_chunks(
        self,
        knowledge_id: str,
        remote_paths: list[str],
        chunk_method: str = "",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separator: list[str] = ["\n"],
        is_generate: bool = False,
        request: Request = None,
        preview_mode: bool = False,
        multimodal_id: str = "",
        is_header_config: bool = False,
        start_line: int = 0,
        end_line: int = 0,
        header_merge_method: str = "",
        is_content_merge: bool = False,
        is_save_image: bool = False,
        use_force_separator: bool = False,
        chunk_type: str = "",
        sub_chunk_size: int = 0,
        sub_separator: list = "",
    ) -> tuple[bool, Any]:
        """
        预览文件切片

        Args:
            knowledge_id: 知识库ID
            remote_paths: 远程文件路径列表
            chunk_method: 切片方式
            chunk_size: 文本块大小
            chunk_overlap: 文本块重叠大小
            separator: 文本分隔符
            is_generate: 是否生成问答对
            request: FastAPI请求对象

        Returns:
            (是否成功, 结果数据)
        """
        local_paths = []
        try:
            # 参数验证
            if chunk_overlap >= chunk_size:
                return False, "分段重叠长度不能大于分段最大长度"

            result = []
            chunk_list = []

            # 处理每个文件
            for remote_path in remote_paths:
                file_name = remote_path.split("/")[-1]
                local_path = f"{self.upload_path}/{file_name}"
                local_paths.append(local_path)

                # 下载文件到本地
                success = await self._download_file_from_remote(remote_path, local_path)
                if not success:
                    return False, "远程服务器下载文件到本地失败"

                # 解析文件
                chunks = await self._parse_and_chunk_file(
                    local_path,
                    knowledge_id,
                    request,
                    chunk_method,
                    chunk_size,
                    chunk_overlap,
                    separator,
                    file_name,
                    preview_mode,
                    multimodal_id,
                    is_header_config,
                    start_line,
                    end_line,
                    header_merge_method,
                    is_content_merge,
                    is_save_image,
                    is_preview=True,
                    use_force_separator=use_force_separator,
                    chunk_type=chunk_type,
                    sub_chunk_size=sub_chunk_size,
                    sub_separator=sub_separator,
                )

                if chunks is None:
                    return False, "文件解析失败"

                chunk_list.extend(chunks)

                # 只取前5个切片用于预览
                if len(chunk_list) > 5:
                    break

            # 生成预览结果
            return await self._generate_preview_result(chunk_list[:5], is_generate, chunk_type)

        except Exception as e:
            logger.error(f"预览文件切片失败: {str(e)}", exc_info=True)
            return False, "预览文件切片错误"
        finally:
            await self._cleanup_local_files(local_paths)

    async def files_parse_preview(
        self,
        file_id: str,
        chunk_method: str,
        chunk_size: int,
        chunk_overlap: int,
        separator: list[str],
        is_generate: bool,
        use_force_separator: bool,
        chunk_type: str = "",
        sub_chunk_size: int = 0,
        sub_separator: list = "",
    ) -> tuple[bool, Any]:
        local_paths = []
        try:
            # 参数验证
            if chunk_overlap >= chunk_size:
                return False, "分段重叠长度不能大于分段最大长度"

            chunks = await self._files_parse_preview(
                file_id,
                chunk_method,
                chunk_size,
                chunk_overlap,
                separator,
                use_force_separator,
                chunk_type,
                sub_chunk_size,
                sub_separator,
            )

            if chunks is None:
                return False, "文件解析失败"

            return await self._generate_preview_result(chunks[:5], is_generate, chunk_type)

        except Exception as e:
            logger.error(f"预览文件切片失败: {str(e)}", exc_info=True)
            return False, "预览文件切片错误"
        finally:
            await self._cleanup_local_files(local_paths)

    async def process_file_upload_batch(
        self,
        knowledge_id: str,
        remote_paths: list[str],
        delete_files: list[str],
        chunk_method: str = "",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        separator: list[str] = ["\n"],
        is_generate: bool = False,
        request: Request = None,
        preview_mode: bool = False,
        multimodal_id: str = "",
        is_header_config: bool = False,
        start_line: int = 0,
        end_line: int = 0,
        header_merge_method: str = "",
        is_content_merge: bool = False,
        is_save_image: bool = False,
        background_tasks: BackgroundTasks | None = None,
        use_force_separator: bool = False,
        chunk_type: Optional[str] = "",
        sub_chunk_size: Optional[int] = 0,
        sub_separator: Optional[list] = "",
    ) -> tuple[bool, str]:
        """
        批量处理文件上传入库

        Args:
            knowledge_id: 知识库ID
            remote_paths: 远程文件路径列表
            delete_files: 要删除的文件ID列表
            chunk_method: 切片方式
            chunk_size: 文本块大小
            chunk_overlap: 文本块重叠大小
            separator: 文本分隔符
            is_generate: 是否生成问答对
            request: FastAPI请求对象

        Returns:
            (是否成功, 消息)
        """
        try:
            # 参数验证
            if chunk_overlap >= chunk_size:
                return False, "分段重叠长度不能大于分段最大长度"

            # 处理删除文件
            await self._handle_file_deletions(knowledge_id, delete_files)

            # 下载远程文件
            local_paths, file_names = await self._download_remote_files(knowledge_id, remote_paths)
            if not local_paths:
                return False, "远程文件下载失败"

            # 检测重复文件
            repeat_files = await Knowledge_File_service.repeat_file_detect(knowledge_id, file_names)
            if repeat_files is False:
                return False, "查询重复文件失败"

            # 文件信息入库
            file_ids = await self._insert_file_info_batch(knowledge_id, file_names, is_save_image)
            task_id_list = []
            # 改为提交 Celery 解析任务（解析完成后任务会继续切片与入库）
            for i in range(len(local_paths)):
                try:
                    if file_names[i] in repeat_files:
                        MongodbUtil.update_docs_by_condition(
                            collection_name="upload_file_info",
                            search_condition={"_id": file_ids[i]},
                            replace_data={"$set": {"status": 3, "info": f"与{file_names[i]}文件重复"}},
                        )
                        logger.info(f"文件<{file_names[i]}>重复了")
                        continue
                    parse_task_id = f"{file_ids[i]}:parse"
                    task_id_list.append(parse_task_id)
                    file_parse_task.apply_async(
                        (
                            local_paths[i],  # local_path
                            knowledge_id,  # knowledge_id
                            False,  # request_data
                            file_names[i],  # file_name
                            file_ids[i],  # file_id
                            preview_mode,  # preview_mode
                            remote_paths[i],  # remote_path
                            chunk_method,  # chunk_method
                            chunk_size,  # chunk_size
                            chunk_overlap,  # chunk_overlap
                            separator,  # separator
                            is_generate,  # is_generate
                            multimodal_id,  # 多模态模型id
                            is_header_config,  # 是否配置表头
                            start_line,  # 起始行
                            end_line,  # 结束行
                            header_merge_method,  # 是否合并表头
                            is_content_merge,  # 是否合并内容
                            is_save_image,  # 是否保存图片
                            use_force_separator,
                            chunk_type,
                            sub_chunk_size,
                            sub_separator,
                        ),
                        task_id=parse_task_id,
                        queue="file_parse",
                    )
                except Exception as e:
                    MongodbUtil.update_one(
                        CollectionConfig.UPLOAD_FILE_INFO_COLLECTION,
                        {"_id": file_ids[i]},
                        {"$set": {"status": 3, "info": str(e)}},
                    )
            return True, "文件上传成功，已提交后台任务处理，请稍等"

        except Exception as e:
            raise

    async def process_file_upload_step_batch(
        self,
        file_id,
        knowledge_id,
        chunk_method,
        chunk_size,
        chunk_overlap,
        separator,
        is_generate,
        use_force_separator,
        chunk_type,
        sub_chunk_size,
        sub_separator,
        background_tasks
    ) -> tuple[bool, str]:
        """
        批量处理文件上传入库

        Args:
            file_id: 文件ID
            knowledge_id: 知识库ID
            chunk_method: 切片方式
            chunk_size: 文本块大小
            chunk_overlap: 文本块重叠大小
            separator: 文本分隔符
            is_generate: 是否生成问答对

        Returns:
            (是否成功, 消息)
        """
        try:
            # 参数验证
            if chunk_overlap >= chunk_size:
                return False, "分段重叠长度不能大于分段最大长度"

            file_info = MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, file_id)
            parse_result_info = MongodbUtil.query_doc_by_id(CollectionConfig.FILE_PARSE_RESULT, file_id)
            parse_result = parse_result_info.get("parse_result", [])
            remote_path = file_info.get("remote_path", "")
            file_name = file_info.get("file_name", "")

            def run_async_task(func, *args, **kwargs):
                asyncio.run(func(*args, **kwargs))

            background_tasks.add_task(
                run_async_task,
                split_embedding_task,
                # await split_embedding_task(
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
                chunk_type,
                sub_chunk_size,
                sub_separator
            )
            return True, "文件上传成功，已提交后台任务处理，请稍等"

        except Exception as e:
            logger.error(f"批量处理文件上传失败: {str(e)}", exc_info=True)
            return False, "上传文件至知识库失败"

    async def _download_file_from_remote(self, remote_path: str, local_path: str) -> bool:
        """从远程下载文件到本地"""
        try:
            await run_in_threadpool(
                MinIoUtil.download_file,
                "tiance-base-temp-file-bucket",
                remote_path,
                local_path,
            )
            logger.info(f"远程文件{remote_path}下载到本地{local_path}成功")
            return True
        except Exception as e:
            logger.info(f"远程服务器下载文件到本地失败: {str(e)}")
            raise

    async def _parse_and_chunk_file(
        self,
        local_path: str,
        knowledge_id: str,
        request: Request,
        chunk_method: str,
        chunk_size: int,
        chunk_overlap: int,
        separator: list[str],
        file_name: str,
        preview_mode: bool = False,
        multimodal_id: str = "",
        is_header_config: bool = False,
        start_line: int = 0,
        end_line: int = 0,
        header_merge_method: str = "",
        is_content_merge: bool = False,
        is_save_image: bool = False,
        is_preview: bool = False,
        file_id: str = "",
        use_force_separator: bool = False,
        chunk_type: str = "",
        sub_chunk_size: int = 0,
        sub_separator: list = "",
        **kwargs,
    ) -> Optional[list[str]]:
        """解析文件并进行切片"""
        try:
            if multimodal_id:
                model_info = MongodbUtil.query_doc_by_id(CollectionConfig.MODEL_RUN_COLLECTION, ObjectId(multimodal_id))
                model_uid = model_info.get("model_uid", "")
                api_url = model_info.get("api_url", f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1")
                api_key = model_info.get("api_key", "not empty")
                is_external = model_info.get("is_external", False)
            else:
                model_uid = ""
                api_url = ""
                api_key = ""
                is_external=""
            start_time = time.time()
            splitter_service = SplitterService()
            # 使用新的文件解析服务
            # set_progress(file_id,"0", 0,time.time())
            parse_result = await self.file_parser.parse_file(
                file_path=local_path,
                knowledge_id=knowledge_id,
                request=request,
                is_preview=is_preview,
                file_name=file_name,
                chunk_method=chunk_method,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=separator,
                file_id=file_id,
                preview_mode=preview_mode,
                multimodal_id=multimodal_id,
                is_header_config=is_header_config,
                start_line=start_line,
                end_line=end_line,
                header_merge_method=header_merge_method,
                is_content_merge=is_content_merge,
                is_save_image=is_save_image,
                model_uid=model_uid,
                api_url=api_url,
                api_key=api_key,
                is_external=is_external,
            )
            set_progress(file_id, "0", 100, time.time())
            end_time = time.time()
            logger.info(f"{local_path}解析文档总耗时为{end_time - start_time}")

            if parse_result is None:
                return None

            # 如果解析结果已经是切片，直接返回
            # if isinstance(parse_result, list) and all(isinstance(item, str) for item in parse_result):
            #     return parse_result

            # 否则提取文本内容进行切片
            # if isinstance(parse_result, dict):
            #     text_content = parse_result.get("text", "")
            #     if text_content and chunk_method:
            #         chunks = await embedding_document(
            #             doc=text_content,
            #             file_name=file_name,
            #             chunk_method=chunk_method,
            #             chunk_size=chunk_size,
            #             chunk_overlap=chunk_overlap,
            #             separator=separator,
            #         )
            #         return chunks if isinstance(chunks, list) else [text_content]
            #     elif text_content:
            #         return [text_content]

            # 如果是字符串，直接处理
            # if isinstance(parse_result, str):
            #     if chunk_method:
            #         chunks = await embedding_document(
            #             doc=parse_result,
            #             file_name=file_name,
            #             chunk_method=chunk_method,
            #             chunk_size=chunk_size,
            #             chunk_overlap=chunk_overlap,
            #             separator=separator,
            #         )
            #         return chunks if isinstance(chunks, list) else [parse_result]
            #     else:
            #         return [parse_result]

            # set_progress(file_id, "1", 0, time.time())
            if isinstance(parse_result, dict):
                try:
                    parse_list = parse_result["results"]["content_list"]
                    if isinstance(parse_result["results"]["content_list"], dict):
                        parse_list = parse_result["results"]["content_list"]["result"]

                except Exception as e:
                    logger.error("解析文件异常失败", exc_info=True)
                    return None
                chunks = await splitter_service.split_text_simple(
                    text=parse_list,
                    method=chunk_method,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    separator=separator,
                    use_force_separator=use_force_separator,
                    is_embedding=kwargs.get("is_embedding", False),
                    chunk_type=chunk_type,
                    sub_chunk_size=sub_chunk_size,
                    sub_separator=sub_separator,
                )
            set_progress(file_id, "1", 100, time.time())
            return chunks

        except Exception as e:
            logger.error(f"文件解析切片失败: {str(e)}", exc_info=True)
            return None

    async def _files_parse_preview(
        self,
        file_id: str,
        chunk_method: str,
        chunk_size: int,
        chunk_overlap: int,
        separator: list[str],
        use_force_separator: bool,
        chunk_type: str = "",
        sub_chunk_size: int = 0,
        sub_separator: list = "",
    ) -> Optional[list[str]]:
        """解析文件并进行切片"""
        try:
            start_time = time.time()
            splitter_service = SplitterService()
            # 使用新的文件解析服务

            file_info = MongodbUtil.query_doc_by_id(CollectionConfig.FILE_PARSE_RESULT, file_id)

            parse_list = file_info["parse_result"]["result"]

            if parse_list is None:
                return None

            chunks = await splitter_service.split_text_simple(
                text=parse_list,
                method=chunk_method,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                separator=separator,
                use_force_separator=use_force_separator,
                chunk_type=chunk_type,
                sub_chunk_size=sub_chunk_size,
                sub_separator=sub_separator,
            )

            return chunks

        except Exception as e:
            logger.error(f"文件解析切片失败: {str(e)}", exc_info=True)
            return None

    async def _generate_preview_result(
        self, chunk_list: list, is_generate: bool, chunk_type: str
    ) -> tuple[bool, list[dict]]:
        """生成预览结果，支持父子分块结构"""
        try:
            result = []

            # 判断是否为父子分块
            if chunk_type != "parent":
                # 传统分块逻辑
                if is_generate:
                    for chunk in chunk_list:
                        try:
                            question = await Knowledge_File_service.generate_question_answer(chunk)
                            question = question.replace("\n", " ").replace("\\n", " ")
                            question_answer = {"QUESTION": question, "ANSWER": chunk}
                            result.append(
                                {"chunk_content": chunk, "question": question, "token": len(str(question_answer))}
                            )
                        except Exception:
                            result.append({"chunk_content": chunk, "question": "问答对生成错误，请重试", "token": 0})
                else:
                    for chunk in chunk_list:
                        result.append({"chunk_content": chunk, "token": len(chunk)})
            else:
                # 父子分块逻辑：按照原逻辑进行返回值的改造
                for chunk_data in chunk_list:
                    if isinstance(chunk_data, dict) and "content" in chunk_data and "metadata" in chunk_data:
                        parent_content = chunk_data["content"]
                        child_chunks = chunk_data["metadata"].get("child_chunks", [])

                        # 处理父级切片
                        if is_generate:
                            try:
                                parent_question = await Knowledge_File_service.generate_question_answer(parent_content)
                                parent_question = parent_question.replace("\n", " ").replace("\\n", " ")
                                parent_question_answer = {"QUESTION": parent_question, "ANSWER": parent_content}
                                parent_result = {
                                    "chunk_content": parent_content,
                                    "question": parent_question,
                                    "token": len(str(parent_question_answer)),
                                    "chunk_type": "parent",
                                }
                            except Exception:
                                parent_result = {
                                    "chunk_content": parent_content,
                                    "question": "问答对生成错误，请重试",
                                    "token": 0,
                                    "chunk_type": "parent",
                                }
                        else:
                            parent_result = {
                                "chunk_content": parent_content,
                                "token": len(parent_content),
                                "chunk_type": "parent",
                            }

                        # 处理子切片
                        child_results = []
                        for child_chunk in child_chunks:
                            if isinstance(child_chunk, dict) and "content" in child_chunk:
                                child_content = child_chunk["content"]

                                if is_generate:
                                    try:
                                        child_question = await Knowledge_File_service.generate_question_answer(
                                            child_content
                                        )
                                        child_question = child_question.replace("\n", " ").replace("\\n", " ")
                                        child_question_answer = {"QUESTION": child_question, "ANSWER": child_content}
                                        child_result = {
                                            "chunk_content": child_content,
                                            "question": child_question,
                                            "token": len(str(child_question_answer)),
                                            "chunk_type": "child",
                                        }
                                    except Exception:
                                        child_result = {
                                            "chunk_content": child_content,
                                            "question": "问答对生成错误，请重试",
                                            "token": 0,
                                            "chunk_type": "child",
                                        }
                                else:
                                    child_result = {
                                        "chunk_content": child_content,
                                        "token": len(child_content),
                                        "chunk_type": "child",
                                    }

                                child_results.append(child_result)

                        parent_result["child_chunks"] = child_results
                        result.append(parent_result)
                    else:
                        # 如果不是预期的父子分块结构，按传统方式处理
                        if is_generate:
                            try:
                                question = await Knowledge_File_service.generate_question_answer(str(chunk_data))
                                question = question.replace("\n", " ").replace("\\n", " ")
                                question_answer = {"QUESTION": question, "ANSWER": str(chunk_data)}
                                result.append(
                                    {
                                        "chunk_content": str(chunk_data),
                                        "question": question,
                                        "token": len(str(question_answer)),
                                    }
                                )
                            except Exception:
                                result.append(
                                    {"chunk_content": str(chunk_data), "question": "问答对生成错误，请重试", "token": 0}
                                )
                        else:
                            result.append({"chunk_content": str(chunk_data), "token": len(str(chunk_data))})

            logger.info("文件预览切片成功")
            return True, result

        except Exception as e:
            logger.error(f"生成预览结果失败: {str(e)}", exc_info=True)
            raise

    async def _handle_file_deletions(self, knowledge_id: str, delete_files: list[str]):
        """处理文件删除"""
        for delete_id in delete_files:
            try:
                file_info = MongodbUtil.query_doc_by_id(CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, delete_id)
                if file_info:
                    file_name = file_info["file_name"]
                    MongodbUtil.del_docs_by_condition(
                        CollectionConfig.UPLOAD_FILE_INFO_COLLECTION, del_condition={"_id": delete_id}
                    )

                    # 这里应该调用删除文件的方法，但原代码中的file_delete方法未定义
                    result = await Knowledge_File_service.delete_file(delete_id, knowledge_id, file_name)
                    logger.info(f"删除文件: {file_name}")

            except Exception as e:
                logger.error(f"删除文件失败: {delete_id}", exc_info=True)
                raise Exception("覆盖文件失败")

    async def _download_remote_files(self, knowledge_id: str, remote_paths: list[str]) -> tuple[list[str], list[str]]:
        """下载远程文件到本地"""
        try:
            local_paths = []
            file_names = []

            for remote_path in remote_paths:
                local_path = ""
                count = 0

                while not os.path.exists(local_path):
                    try:
                        local_path = f"{self.upload_path}/{remote_path.split('/')[1]}$$${remote_path.split('/')[-1]}"
                        local_path = os.path.abspath(local_path).replace("\\", "/")

                        await run_in_threadpool(
                            MinIoUtil.download_file,
                            "tiance-base-temp-file-bucket",
                            remote_path,
                            local_path,
                        )

                        await asyncio.sleep(0.1)

                        if os.path.exists(local_path):
                            file_names.append(remote_path.split("/")[-1])
                            local_paths.append(local_path)
                            logger.info(f"远程文件下载到本地<<<{local_path}>>>成功")
                            break
                        else:
                            count += 1

                        if count == 3:
                            raise Exception("远程文件下载失败")

                    except Exception as e:
                        logger.error(f"远程文件下载失败: {str(e)}", exc_info=True)
                        raise Exception("远程文件下载失败")

            return local_paths, file_names
        except Exception as e:
            logger.info(f"远程文件下载失败{str(e)}")

    async def _insert_file_info_batch(self, knowledge_id: str, file_names: list[str], is_save_image: bool) -> list[str]:
        """批量插入文件信息"""
        try:
            file_ids = []

            for file_name in file_names:
                try:
                    result, file_id = await Knowledge_File_service.insert_file_info(knowledge_id, file_name, is_save_image)
                    file_ids.append(file_id)
                    await asyncio.sleep(0.1)
                    logger.info(f"文档{file_name}信息入库成功")
                except Exception as e:
                    logger.error(f"文档{file_name}信息入库出错", exc_info=True)
                    file_ids.append("")  # 添加空字符串保持索引对应

            return file_ids
        except Exception as e:
            logger.info(f"文件基础信息入库失败{str(e)}")
            raise

    # async def _process_files_in_background(
    #     self,
    #     knowledge_id: str,
    #     remote_paths: list[str],
    #     chunk_method: str,
    #     chunk_size: int,
    #     chunk_overlap: int,
    #     separator: list[str],
    #     is_generate: bool,
    #     local_paths: list[str],
    #     file_ids: list[str],
    #     repeat_files: list[str],
    #     file_names: list[str],
    #     request: Request,
    # ):
    #     """在后台处理文件"""
    #     try:
    #         # 标记重复文件
    #         for repeat_file in repeat_files:
    #             MongodbUtil.update_docs_by_condition(
    #                 "upload_file_info",
    #                 {"id": knowledge_id, "file_name": repeat_file, "status": 1},
    #                 replace_data={"$set": {"status": 2, "info": f"与{repeat_file}文件重复"}},
    #             )
    #             logger.info(f"文件<{repeat_file}>重复了")
    #
    #         # 处理每个文件
    #         for i in range(len(local_paths)):
    #             file_name = file_names[i]
    #             if file_name in repeat_files:
    #                 continue
    #
    #             file_id = file_ids[i]
    #             logger.info(f"开始执行文件：{local_paths[i]}")
    #
    #             try:
    #                 await self._process_single_file(
    #                     knowledge_id,
    #                     local_paths[i],
    #                     file_name,
    #                     file_id,
    #                     chunk_method,
    #                     chunk_size,
    #                     chunk_overlap,
    #                     separator,
    #                     is_generate,
    #                     remote_paths[i],
    #                     request,
    #                 )
    #             except Exception as e:
    #                 logger.error(f"处理文件失败: {file_name}", exc_info=True)
    #                 MongodbUtil.update_docs_by_condition(
    #                     "upload_file_info",
    #                     {"knowledge_id": knowledge_id, "file_name": file_name, "status": 1},
    #                     replace_data={"$set": {"status": 2, "info": str(e)}},
    #                 )
    #
    #         logger.info("文件切块入库成功")
    #
    #     except Exception as e:
    #         logger.error(f"后台处理文件失败: {str(e)}", exc_info=True)
    #     finally:
    #         await self._cleanup_local_files(local_paths)

    # async def _process_single_file(
    #     self,
    #     knowledge_id: str,
    #     local_path: str,
    #     file_name: str,
    #     file_id: str,
    #     chunk_method: str,
    #     chunk_size: int,
    #     chunk_overlap: int,
    #     separator: list[str],
    #     is_generate: bool,
    #     remote_path: str,
    #     request: Request,
    # ):
    #     """处理单个文件"""
    #     try:
    #         # 设置进度
    #         set_progress(file_id, "0", 0.0, time.time())
    #
    #         # 解析文件
    #         chunks = await self._parse_and_chunk_file(
    #             local_path,
    #             knowledge_id,
    #             request,
    #             chunk_method,
    #             chunk_size,
    #             chunk_overlap,
    #             separator,
    #             file_name,
    #             is_preview=False,
    #             file_id=file_id,
    #             is_embedding=True,
    #         )
    #         print("chunk", chunks)
    #         if chunks is None:
    #             raise Exception("文件解析失败")
    #
    #         set_progress(file_id, "0", 100.0, time.time())
    #
    #         # 向量化入库
    #         if is_generate:
    #             result = await Knowledge_File_service.add_embedding_document(
    #                 knowledge_id,
    #                 chunks,
    #                 file_name,
    #                 chunk_method,
    #                 chunk_size,
    #                 chunk_overlap,
    #                 separator,
    #                 file_id,
    #                 [],
    #                 [],
    #                 [],
    #                 [],
    #             )
    #         else:
    #             print("chunk", chunks)
    #             result, info = await Knowledge_File_service.add_embedding_document_without_question(
    #                 knowledge_id,
    #                 chunks,
    #                 file_name,
    #                 chunk_method,
    #                 chunk_size,
    #                 chunk_overlap,
    #                 separator,
    #                 file_id,
    #                 [],
    #                 [],
    #                 [],
    #                 [],
    #             )
    #
    #         # 更新文件状态
    #         if result:
    #             MongodbUtil.update_docs_by_condition(
    #                 "upload_file_info",
    #                 {"knowledge_id": knowledge_id, "file_name": file_name},
    #                 replace_data={
    #                     "$set": {
    #                         "status": 0,
    #                         "remote_path": f"{knowledge_id}/{file_name}",
    #                     }
    #                 },
    #             )
    #
    #             # 复制文件到正式存储
    #             MinIoUtil.copy_object(
    #                 "tiance-base-temp-file-bucket",
    #                 remote_path,
    #                 "tiance-base",
    #                 f"{knowledge_id}/{file_name}",
    #             )
    #         else:
    #             error_info = info if not is_generate else "向量化失败"
    #             MongodbUtil.update_docs_by_condition(
    #                 "upload_file_info",
    #                 {"knowledge_id": knowledge_id, "file_name": file_name, "status": 1},
    #                 replace_data={"$set": {"status": 2, "info": str(error_info)}},
    #             )
    #
    #     except Exception as e:
    #         logger.error(f"处理单个文件失败: {file_name}", exc_info=True)
    #         raise

    async def _cleanup_local_files(self, local_paths: list[str]):
        """清理本地临时文件"""
        for local_path in local_paths:
            try:
                if os.path.exists(local_path):
                    os.remove(local_path)
                    logger.info(f"清理临时文件: {local_path}")
            except Exception as e:
                logger.error(f"清理临时文件失败: {local_path}", exc_info=True)

    async def save_kb_arrange_info(
        self,
        id,
        chunk_method,
        chunk_overlap,
        chunk_size,
        is_generate,
        separator,
        use_force_separator,
        chunk_type,
        sub_chunk_size,
        sub_separator,
    ):
        kb_arrange_data = {
            "_id": ObjectId(id),
            "chunk_method": chunk_method,
            "chunk_overlap": chunk_overlap,
            "chunk_size": chunk_size,
            "is_generate": is_generate,
            "separator": separator,
            "use_force_separator": use_force_separator,
            "chunk_type": chunk_type,
            "sub_chunk_size": sub_chunk_size,
            "sub_separator": sub_separator,
        }
        kb_result = MongodbUtil.query_doc_by_id(CollectionConfig.KB_ARRANGE_INFO, ObjectId(id))
        if not kb_result:
            logger.info("kb_result新增成功")
            MongodbUtil.insert_one(CollectionConfig.KB_ARRANGE_INFO, kb_arrange_data)
            return True
        elif kb_result.get("chunk_type", "") == "null" or kb_result.get("chunk_type", "") =="":
            logger.info("kb_result新增成功")
            # 添加警告，不允许和已有的chunk_type重复
            return True
        elif kb_result.get("chunk_type", "") != chunk_type:
            logger.info("kb_result和数据库不同")
            # 添加警告，不允许和已有的chunk_type重复
            return False
        else:
            logger.info("更新kb_info")
            # 更新已有数据
            MongodbUtil.update_one(
                CollectionConfig.KB_ARRANGE_INFO,
                {"_id": ObjectId(id)},
                {
                    "$set": {
                        "chunk_overlap": chunk_overlap,
                        "chunk_size": chunk_size,
                        "is_generate": is_generate,
                        "separator": separator,
                        "use_force_separator": use_force_separator,
                        "chunk_type": chunk_type,
                        "sub_chunk_size": sub_chunk_size,
                        "sub_separator": sub_separator,
                        "chunk_method": chunk_method,
                    }
                },
            )
            return True


# 全局服务实例
file_processing_service = FileProcessingService()
