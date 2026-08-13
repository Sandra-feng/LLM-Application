
from loguru import logger
import os

import aiofiles
import requests
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from base_utils.minio_util import MinIoUtil
from base_utils.ret_util import RetUtil
# logger = loguru logger (auto-migrated)
class FileService:
    """
    文件上传下载服务
    """

    @staticmethod
    async def get_upload_file_urls(file_list):
        """
        上传多个文件并获取文件地址列表
        :param file_list: 包含(file_name, file_type, file_obj)的列表
        :return: 文件地址列表
        """
        file_urls = []

        for file_name, file_type, file_obj in file_list:
            local_path = rf"D:\BASELLM\tiance-base\{file_name}"

            try:
                # 异步写入文件内容
                async with aiofiles.open(local_path, "wb") as temp_file:
                    content = await file_obj.read()
                    await temp_file.write(content)

                # 上传文件到 MinIO
                remote_path = f"pytest/{file_name}"  # 可以根据需求修改路径或文件名
                bucket_name = "tiance-base"
                await run_in_threadpool(MinIoUtil.upload_file, bucket_name, remote_path, local_path)

                # 生成文件访问 URL
                file_url = MinIoUtil.min_io_client.presigned_get_object(bucket_name, remote_path)
                file_urls.append(file_url)  # 保存文件 URL 列表

            except (Exception, RuntimeError) as e:
                logger.error("文件地址返回失败", exc_info=True)
                # 可以选择返回错误信息，或者继续尝试上传其他文件
                return RetUtil.response_error(message="文件地址返回失败")

            finally:
                if os.path.exists(local_path):
                    os.remove(local_path)
        file_urls = {"file_url": file_urls}
        return file_urls

    @staticmethod
    async def get_stream_response(file_name, file_url):
        response = requests.get(file_url, stream=True)
        response.raise_for_status()  # 检查请求是否成功

        # 创建生成器函数来逐块读取内容
        def iterfile():
            for chunk in response.iter_content(chunk_size=1024):
                yield chunk

        # 使用 StreamingResponse 实现流式返回
        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename={file_name}"},
        )
