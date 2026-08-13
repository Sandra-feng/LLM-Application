#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：file_upload_download.py
@Author  ：YunPeng
@Date    ：2024/8/28 9.17
"""

from loguru import logger
from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import Response, StreamingResponse

from base_utils.ret_util import RetUtil
from service_config_manage.service.file_upload_download_service import FileService
# logger = loguru logger (auto-migrated)
router = APIRouter()


@router.post("/upload_file", description="上传文件")
async def upload_files(
    file_names: list[str] = Form(...),  # 文件名称列表
    file_types: list[str] = Form(...),  # 文件类型列表
    files: list[UploadFile] = File(...),  # 接收的文件列表
) -> Response:
    try:
        file_names = file_names[0].replace("'", "")
        file_types = file_types[0].replace("'", "")
        # 这里假设 FileService 有一个可以接受文件列表的方法
        file_names = file_names.split(",") if isinstance(file_names, str) else file_names
        file_types = file_types.split(",") if isinstance(file_types, str) else file_types

        # 创建文件列表
        file_list = [
            (file_name, file_type, file_obj) for file_name, file_type, file_obj in zip(file_names, file_types, files)
        ]
        file_urls = await FileService.get_upload_file_urls(file_list)

        return RetUtil.response_ok(data=file_urls)

    except (Exception, RuntimeError) as e:
        logger.error("文件上传失败", exc_info=True)
        return RetUtil.response_error(message="文件上传失败")


@router.get("/download_file", description="下载文件")
async def download_file(
    file_name: str = Query(..., examples=["1.png"], description="文件名称"),
    file_url: str = Query(
        ...,
        examples=["http://192.168.33.142:9000/tiance-base/pytest/%E8%B5%B5%E9%B9%8F%E9%A3%9E.md%2"],
        description="文件地址",
    ),
) -> StreamingResponse:
    try:
        stream_response = await FileService.get_stream_response(file_name, file_url)
        return stream_response
    except (Exception, RuntimeError) as e:
        logger.error("文件下载失败 | file_name=%s | file_url=%s", file_name, file_url, exc_info=True)
        return RetUtil.response_error(message="文件下载失败")
