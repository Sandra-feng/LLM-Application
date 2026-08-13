# vscode调试专用代码

import sys
from pathlib import Path

# 将当前文件所在目录加入到sys.path，方便本地调试和模块导入
# 由于直接将当前目录加入sys.path可能导致导入失败，改为将项目根目录加入sys.path
project_root = str(Path(__file__).resolve().parents[2])
if project_root not in sys.path:
    sys.path.insert(0, project_root)


import asyncio
import os
from pathlib import Path
from typing import Any, Optional

from fastapi import Request
from loguru import logger

from service_knowledge_manage.service.parsers import BasicParser, ExcelParser, PdfParser


class FileParseService:
    """
    文件解析服务。
    根据文件类型分派给相应的解析器，并处理Office文件的转换。
    """

    def __init__(self):
        """初始化文件解析服务"""
        self.logger = logger
        self._init_parsers()
        self.temp_dir = Path(__file__).resolve().parents[0] / "result" / "transformer"
        os.makedirs(self.temp_dir, exist_ok=True)

    def _init_parsers(self):
        """初始化并注册所有解析器"""
        try:
            # 初始化具体的解析器
            basic_parser = BasicParser()
            excel_parser = ExcelParser()
            pdf_parser = PdfParser()

            # 注册解析器到文件扩展名
            self.parser_map = {
                **dict.fromkeys([".txt", ".md", ".html"], basic_parser),
                **dict.fromkeys([".xls", ".xlsx", ".csv"], excel_parser),
                **dict.fromkeys([".pdf", ".png", ".jpg", ".jpeg"], pdf_parser),
            }

            # 需要转换为PDF再用PDF解析器处理的格式
            self.office_to_pdf_formats = [".doc", ".docx", ".ppt", ".pptx"]

            self.logger.debug(f"解析器映射已初始化: {list(self.parser_map.keys())}")
            self.logger.debug(f"Office转PDF格式: {self.office_to_pdf_formats}")
        except Exception:
            self.logger.exception("初始化解析器失败")
            raise

    async def parse_file(
        self, file_path: str, knowledge_id: str, request: Request, is_preview: bool = False, **kwargs
    ) -> Optional[dict[str, Any]]:
        """
        解析文件的主入口点。

        它会根据文件扩展名选择合适的解析器。
        对于 .doc /.docx / .ppt / .pptx 文件，它会先将其转换为 PDF，然后再使用PDF解析器进行处理。

        Args:
            file_path (str): 要解析的文件的路径。
            knowledge_id (str): 知识库ID。
            request (Request): FastAPI 请求对象。
            is_preview (bool): 是否为预览模式。
            **kwargs: 其他参数。

        Returns:
            一个包含解析结果的字典，如果解析失败则返回 None。
        """
        self.logger.info(f"开始解析文件: {file_path}, 知识库ID: {knowledge_id}, 预览模式: {is_preview}")
        # 检查文件是否存在
        if not os.path.exists(file_path):
            self.logger.error(f"文件不存在: {file_path}")
            return None

        ext = os.path.splitext(file_path)[-1].lower()
        parser = self.parser_map.get(ext)
        temp_pdf_path = None
        temp_pdf_dir = None

        try:
            if ext in self.office_to_pdf_formats:
                # 对于doc/docx，先转换为PDF
                self.logger.info(f"检测到Office文件格式 {ext}，开始转换为PDF")
                parser = self.parser_map[".pdf"]  # 使用PDF解析器
                temp_pdf_path, temp_pdf_dir = self._convert_to_pdf(file_path)
                if not temp_pdf_path:
                    raise Exception(f"文件转换PDF失败: {file_path}")
                parse_path = temp_pdf_path
                self.logger.info(f"Office文件转换完成，使用PDF解析器处理: {parse_path}")

            elif parser:
                self.logger.info(f"使用 {type(parser).__name__} 解析器处理文件: {file_path}")
                parse_path = file_path
            else:
                supported = list(self.parser_map.keys()) + self.office_to_pdf_formats
                self.logger.warning(f"不支持的文件格式: {ext}。支持的格式有: {supported}")
                raise ValueError(f"不支持的文件格式: {ext}")

            # 调用解析器进行解析
            result = await parser.parse(
                file_path=parse_path,
                knowledge_id=knowledge_id,
                request=request,
                is_preview=is_preview,
                **kwargs,
            )

            if result:
                self.logger.info(f"文件解析成功: {file_path}")
            else:
                self.logger.warning(f"文件解析返回空结果: {file_path}")

            return result
        except Exception:
            self.logger.exception(f"解析文件 '{os.path.basename(file_path)}' 时出错")
            raise
        finally:
            # 清理转换过程中生成的临时目录
            if temp_pdf_dir and os.path.exists(temp_pdf_dir):
                try:
                    import shutil

                    shutil.rmtree(temp_pdf_dir)
                    self.logger.debug(f"成功清理临时目录: {temp_pdf_dir}")
                except OSError:
                    self.logger.exception(f"清理临时目录失败: {temp_pdf_dir}")

    def _convert_to_pdf(self, file_path: str) -> Optional[str]:
        """
        使用 LibreOffice (soffice) 将文件转换为 PDF。

        Args:
            file_path (str): 源文件路径。

        Returns:
            转换后的PDF文件路径，如果失败则返回 None。
        """
        self.logger.info(f"开始将 {file_path} 转换为 PDF...")
        self.logger.debug(f"临时目录: {self.temp_dir}")

        try:
            # 使用同步方式运行 soffice 命令
            import shutil
            import subprocess
            import uuid

            # 为并发安全：每次转换使用独立的输出目录与独立的 LibreOffice 用户配置目录
            unique_suffix = uuid.uuid4().hex
            job_out_dir = os.path.join(self.temp_dir, f"job_{unique_suffix}")
            profile_dir = os.path.join(self.temp_dir, f"lo_profile_{unique_suffix}")
            os.makedirs(job_out_dir, exist_ok=True)
            os.makedirs(profile_dir, exist_ok=True)

            # LibreOffice 的 UserInstallation 需要 file URI 形式
            try:
                profile_uri = Path(profile_dir).resolve().as_uri()
            except Exception:
                # 兜底（极端情况下 as_uri 失败时），尽力构造 file:// URI
                profile_uri = f"file:///{Path(profile_dir).resolve().as_posix()}"

            # 更稳健的启动参数，避免首次启动、锁检查、恢复对话框等交互引起的阻塞
            cmd = [
                "soffice",
                "--headless",
                "--nologo",
                "--nolockcheck",
                "--norestore",
                "--nodefault",
                "--nocrashreport",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(job_out_dir),
                file_path,
            ]
            self.logger.debug(f"执行命令: {' '.join(cmd)}")

            # 运行转换
            process = subprocess.run(
                cmd,
                capture_output=True,
                timeout=300,  # 5分钟超时
            )

            if process.returncode != 0:
                error_msg = process.stderr.decode("utf-8", "ignore")
                stdout_msg = process.stdout.decode("utf-8", "ignore")
                self.logger.error(f"Soffice 转换失败 (code {process.returncode})")
                self.logger.error(f"错误输出: {error_msg}")
                if stdout_msg:
                    self.logger.error(f"标准输出: {stdout_msg}")
                return None

            original_basename = os.path.basename(file_path)
            pdf_filename = os.path.splitext(original_basename)[0] + ".pdf"
            output_path = os.path.join(job_out_dir, pdf_filename)

            self.logger.debug(f"期望的输出文件路径: {output_path}")

            if os.path.exists(output_path):
                file_size = os.path.getsize(output_path)
                self.logger.info(f"文件成功转换为: {output_path} (大小: {file_size} 字节)")
                return output_path, job_out_dir
            else:
                self.logger.error(f"Soffice 转换后未找到输出文件: {output_path}")
                # 列出临时目录中的文件，帮助调试
                try:
                    temp_files = os.listdir(job_out_dir)
                    self.logger.debug(f"临时目录中的文件: {temp_files}")
                except Exception as e:
                    self.logger.debug(f"无法列出临时目录内容: {e}")
                return None, None
        except FileNotFoundError:
            self.logger.exception("`soffice` 命令未找到。请确保 LibreOffice 已安装并已添加到系统PATH中。")
            return None, None
        except Exception:
            self.logger.exception("文件转换期间发生未知错误")
            return None, None
        finally:
            # 清理临时的 LibreOffice 用户配置目录与输出目录
            try:
                if "profile_dir" in locals() and os.path.isdir(profile_dir):
                    shutil.rmtree(profile_dir, ignore_errors=True)
                # 输出目录可能被上层继续使用（例如后续还要读取），仅在失败或上层已处理后清理
                # 这里不强制删除 job_out_dir，交由 finally 外层逻辑根据需要决定
            except Exception as _:
                pass

    # 向后兼容的方法
    # TODO: 删除
    @staticmethod
    async def file_to_text(file_path: str, request: Request):
        """向后兼容的方法 - 基础文件解析"""
        # logger = loguru logger (auto-migrated)
        logger.info(f"调用向后兼容方法 file_to_text: {file_path}")
        service = FileParseService()
        return await service.parse_office_file(file_path, request, convert_to_pdf=False)

    # TODO: 删除
    @staticmethod
    async def file_to_text_preview(file_path: str, page: int, request: Request):
        """向后兼容的方法 - 文件预览"""
        # logger = loguru logger (auto-migrated)
        logger.info(f"调用向后兼容方法 file_to_text_preview: {file_path}, 页码: {page}")
        service = FileParseService()
        return await service.parse_office_file(file_path, request, convert_to_pdf=True)


# 为了向后兼容，保留原有的类名
class VectorDatabaseService(FileParseService):
    """向后兼容的类名，建议使用FileParseService"""

    pass

    # INSERT_YOUR_CODE


if __name__ == "__main__":
    import asyncio

    class DummyRequest:
        """用于模拟FastAPI的Request对象"""

        app = type("App", (), {"state": type("State", (), {"text": None})})()

    async def main():
        file_path = r"E:\Test_files\PDF\Dolphin.pdf"
        request = DummyRequest()
        print("开始测试 FileParseService...")
        service = FileParseService()
        # 只测试 parse_file 方法
        print("测试 parse_file 方法：")
        result = await service.parse_file(file_path, "6819c37c3d11daef7e42c1d0", request)
        print("parse_file 结果：", result)

    asyncio.run(main())
