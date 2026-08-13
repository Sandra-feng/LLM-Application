import os
from typing import Any

import httpx
from loguru import logger

from base_configs.api_config import ApiConfig
from base_configs.model_config import ModelConfig
from service_knowledge_manage.service.parsers.base_parser import BaseParser


class PdfParser(BaseParser):
    """
    pdf文件解析器, 调用远程PDF解析服务进行深度解析。
    支持pdf、png、jpg、jpeg文件解析。
    """

    def __init__(self):
        # 远程PDF解析服务配置
        self.pdf_service_url = ApiConfig.Small_Model_Address  # 根据实际服务地址配置
        self.timeout = 1800  # 30分钟超时

    async def parse(self, file_path: str, **kwargs) -> dict[str, Any]:
        """
        使用远程PDF解析服务解析PDF文件。

        Args:
            file_path (str): PDF文件路径
            **kwargs: 其他参数，包括knowledge_id, file_name, file_id等

        Returns:
            dict: 包含解析结果的字典
        """
        try:
            use_vlm_mode = False
            knowledge_id = kwargs.get("knowledge_id", "")
            model_uid = kwargs.get("model_uid", "")
            api_url = kwargs.get("api_url", "")
            api_key = kwargs.get("api_key", "") if kwargs.get("is_external", False) else ModelConfig.LLM_API_KEY

            # 如果model_uid和api_url和api_key不为空，则使用vlm模式
            if model_uid and api_url and api_key:
                use_vlm_mode = True

            # 调用的参数
            logger.info(f"调用的参数为: {use_vlm_mode}, {knowledge_id}, {model_uid}, {api_url}")

            # 调用远程PDF解析服务
            result = await self._call_remote_pdf_service(
                file_path=file_path,
                knowledge_id=knowledge_id,
                use_vlm_mode=use_vlm_mode,
                model_uid=model_uid,
                api_url=api_url,
                api_key=api_key,
            )

            return result

        except Exception:
            logger.exception("PDF解析失败")
            raise

    async def _call_remote_pdf_service(
        self,
        file_path: str,
        knowledge_id: str,
        use_vlm_mode: bool,
        model_uid: str,
        api_url: str,
        api_key: str,
    ) -> dict[str, Any]:
        """调用远程PDF解析服务"""
        try:
            # 准备文件数据
            with open(file_path, "rb") as f:
                file_data = f.read()

            # 根据文件类型准备不同的表单数据
            ext = os.path.splitext(file_path)[-1].lower()
            if ext == ".pdf":
                mime_type = "application/pdf"
            elif ext in [".png"]:
                mime_type = "image/png"
            elif ext in [".jpg", ".jpeg"]:
                mime_type = "image/jpeg"
            else:
                mime_type = "application/octet-stream"
            files = [("files", (os.path.basename(file_path), file_data, mime_type))]
            data = {
                "output_dir": "./output",  # 输出目录
                "backend": "pipeline",  # 后端
                "parse_method": "auto",  # 解析方法
                "formula_enable": "true",  # 公式
                "table_enable": "true",  # 表格
                "server_url": "",  # 服务URL
                "return_md": "false",  # 返回MD
                "return_middle_json": "false",  # 返回中间JSON
                "return_model_output": "false",  # 返回模型输出
                "return_content_list": "true",  # 返回内容列表
                "return_images": "false",  # 返回图像
                "start_page_id": "0",  # 开始页ID
                "end_page_id": "99999",  # 结束页ID
                "enable_minio": "True",  # 是否启用MinIO
                "minio_bucket": "tiance-base",
                "knowledge_id": knowledge_id,
                "use_vlm_mode": use_vlm_mode,  # 是否使用vlm模式对图片生成描述
                "model_uid": model_uid,  # 模型UID
                "api_url": api_url,  # 接口URL
                "api_key": api_key,  # 接口密钥
            }

            # 调用远程服务
            async with httpx.AsyncClient(
                base_url=f"{self.pdf_service_url}",
                timeout=self.timeout,
                headers={"Connection": "keep-alive"},
                http2=True,
            ) as client:
                response = await client.post("/file_parse", files=files, data=data)
                response.raise_for_status()
                try:
                    return response.json()
                except Exception:
                    logger.exception(f"解析PDF服务返回的JSON失败: {response.content}")
                    raise Exception("远程PDF服务返回内容不是有效的JSON格式")

        except httpx.HTTPStatusError as e:
            logger.exception(f"远程PDF服务调用失败: {e.response.status_code} - {e.response.text}")
            raise
        except Exception:
            logger.exception("调用远程PDF服务异常")
            raise
