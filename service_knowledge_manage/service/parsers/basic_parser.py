import asyncio
import io
import os
import time
import uuid
from typing import Any

import httpx
import mistune
import requests
from bs4 import BeautifulSoup
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from base_utils.minio_util import MinIoUtil
from service_knowledge_manage.service.parsers.base_parser import BaseParser

img_prompt = """
## 角色
你是一个专业的图像内容解析助手，能够精准识别图中的内容，并根据不同内容形式进行恰当输出。

## 技能
### 技能 1: 解析表格
1. 当识别到图中内容为表格时，以标准的 md 样式输出表格内容。

### 技能 2: 解析文字
1. 当识别到图中内容为文字时，直接输出文字内容。

### 技能 3: 解析其他样式内容
1. 当识别到图中为其他样式的内容时，按照简洁清晰的语句来描述该内容。

## 限制:
- 仅回答与解析图中内容相关的问题，拒绝回答无关话题。
- 输出内容需符合对应技能要求的格式。
"""


class BasicParser(BaseParser):
    """
    基础文件解析器，用于处理 txt, md, html 等文件。
    """

    async def parse(self, file_path: str, **kwargs) -> dict[str, Any]:
        """
        使用解析服务解析文件。

        Args:
            file_path (str): 文件路径。

        Returns:
            一个包含文本和元数据的字典。
        """
        try:
            use_vlm_mode = False
            knowledge_id = kwargs.get("knowledge_id", "")
            model_uid = kwargs.get("model_uid", "")
            api_url = kwargs.get("api_url", "")
            api_key = kwargs.get("api_key", "")
            pdf_service_url = "http://10.8.21.165:8100"
            assert os.path.exists(file_path), "该文件路径不存在"
            assert file_path.endswith((".html", ".md", ".txt")), "该解析器目前赞不支持该文件的解析"
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            if file_path.endswith(".md"):
                my_md = MarkdownParse(content, knowledge_id, use_vlm_mode, model_uid, api_url, api_key, pdf_service_url)
                node_list = await my_md.run()
                return {
                    "status": "success",
                    "knowledge_id": knowledge_id,
                    "results": {"content_list": await self.source_mount(node_list)},
                }
            elif file_path.endswith(".html"):
                my_ht = HtmlParse(content, knowledge_id, use_vlm_mode, model_uid, api_url, api_key, pdf_service_url)
                node_list = await my_ht.run()
                return {
                    "status": "success",
                    "knowledge_id": knowledge_id,
                    "results": {"content_list": await self.source_mount(node_list)},
                }
            elif file_path.endswith(".txt"):
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                content_list = [
                    {
                        "type": "text",
                        "text": line,
                        "id": str(uuid.uuid4()),
                        "page_idx": 0,
                        "referenced_images": [],
                        "referenced_tables": [],
                    }
                    for line in lines
                ]
                return {
                    "status": "success",
                    "knowledge_id": knowledge_id,
                    "results": {
                        "content_list": content_list,
                    },
                }
            return {}
        except Exception:
            logger.exception(f"解析文件 '{os.path.basename(file_path)}' 时出错")
            raise

    @staticmethod
    async def source_mount(node_list):
        """
        将解析出来的node列表转为可以返回的形式。将图片、表格挂载到对应的node上。
        html文件的type有text、image、table、audio、
        md文件的type有text、image、table、
        """
        try:
            content_list = []
            for node_id in range(len(node_list)):
                node = node_list[node_id]
                if node.type == "text":
                    content_list.append(
                        {
                            "type": "text",
                            "text": node.text,
                            "id": str(uuid.uuid4()),
                            "page_idx": 0,
                            "referenced_images": node.mount_data_image,
                            "referenced_tables": node.mount_data_table,
                        }
                    )
                elif node.type in ["image", "table"]:
                    node_uuid = str(uuid.uuid4())
                    content_list.append(
                        {
                            "type": node.type,
                            "text": node.text,
                            "id": node_uuid,
                            "page_idx": 0,
                            "referenced_images": [],
                            "referenced_tables": [],
                            "img_path": node.source_data if node.source_data else "",
                            "caption": [node.theme],
                        }
                    )
                    # 先向上搜索30个node，再向下搜索30个node。使用theme字符串匹配text。
                    if not node.theme or not node.source_data:
                        # 没有theme或者source_data，只加入节点
                        continue
                    node_jd = node_id - 1
                    count = 30
                    acc_judge = 0
                    while node_jd >= 0 and count >= 1:
                        if node_list[node_jd].type == "text" and node_list[node_jd].text:
                            # 只有是text节点，且存在text，才进行匹配和匹配计数
                            if node.theme in node_list[node_jd].text:
                                # 匹配成功
                                assert content_list[node_jd]["text"] == node_list[node_jd].text, (
                                    "挂载资源匹配到的文本段在之前加入的文本段中找不到"
                                )
                                if node.type == "image":
                                    content_list[node_jd]["referenced_images"].append(node_uuid)
                                    logger.info(f"->挂载图片成功：{node_jd}")
                                elif node.type == "table":
                                    content_list[node_jd]["referenced_tables"].append(node_uuid)
                                    logger.info(f"->挂载表格成功：{node_jd}")
                                acc_judge = 1
                                break
                            else:
                                # 匹配失败，匹配下一条
                                count -= 1
                        node_jd -= 1
                    if not acc_judge:
                        # 向上搜索失败，先下搜索
                        node_jd = node_id + 1
                        count = 30
                        while node_jd < len(node_list) and count >= 1:
                            if node_list[node_jd].type == "text" and node_list[node_jd].text:
                                # 只有是text节点，且存在text，才进行匹配和计数
                                if node.theme in node_list[node_jd].text:
                                    # 匹配成功，这里处理node_list，后面遍历到的时候会直接加入到content_list
                                    if node.type == "image":
                                        node_list[node_jd].mount_data_image.append(node_uuid)
                                        logger.info(f"->挂载图片成功：{node_jd}")
                                    elif node.type == "table":
                                        node_list[node_jd].mount_data_table.append(node_uuid)
                                        logger.info(f"->挂载表格成功：{node_jd}")
                                    break
                                else:
                                    # 匹配失败，下一条
                                    count -= 1
                            node_jd += 1
            return content_list
        except Exception as e:
            logger.info(f"返回node列表失败，失败原因：{str(e)}")
            raise


class Node:
    def __init__(self, my_type, source_data, text, theme):
        # 节点类型
        self.type = my_type
        # Minio路径
        self.source_data = source_data
        # 获取到的文本或者图像描述
        self.text = text
        # 用于将图像匹配到文本
        self.theme = theme
        # 用于记录source_data的Minio路径，只在source_mount函数用得到
        self.mount_data_image = []
        self.mount_data_table = []


async def download_image(
    url, knowledge_id, use_vlm_mode, model_uid, api_url, api_key, pdf_service_url, timeout=5, max_retries=5
):
    """
    获取图片（本地或者网络路径），存入Minio，返回Minio中的图像路径
    """
    try:
        # 本地路径
        # if os.path.exists(url):
        #     with open(url, "rb") as f:
        #         f_bytes = f.read()
        #     img_stream = io.BytesIO(f_bytes)
        #     img = Image.open(img_stream)
        #     if img.mode != "RGB":
        #         img = img.convert("RGB")
        #     # 存入Minio中
        #     img_stream.seek(0)
        #     img_path = f"multimode/{str(uuid.uuid4())}.jpg"
        #     write_result = MinIoUtil.min_io_client.put_object(
        #         "tiance-base",
        #         img_path,
        #         img_stream,
        #         img_stream.getbuffer().nbytes,  # 数据长度
        #         "image/jpg",
        #     )
        #     logger.info(f"->上传图片成功：{write_result.object_name}")
        #     # 获取图像描述
        #     image_chat = Llm_Service_vllm()
        #     base64_page_image = image_chat.encode_image(img)
        #     image_response = image_chat.answer_question_for_vl(img_prompt, base64_page_image)
        #     logger.info(f"->获取图片的大模型问答成功")

        if os.path.exists(url):
            with open(url, "rb") as f:
                file_data = f.read()
            # 调用解析服务
            ext = os.path.splitext(url)[-1].lower()
            if ext in [".jpg", ".jpeg"]:
                mime_type = "image/jpeg"
            elif ext == ".png":
                mime_type = "image/png"
            else:
                mime_type = "application/octet-stream"
            files = [("files", (os.path.basename(url), file_data, mime_type))]
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
                "enable_minio": "False",  # 是否启用MinIO
                "minio_bucket": "tiance-base",
                # "use_vlm_mode": use_vlm_mode,  # 是否使用vlm模式对图片生成描述
                # "model_uid": model_uid,  # 模型UID
                # "api_url": api_url,  # 接口URL
                # "api_key": api_key,  # 接口密钥
            }
            async with httpx.AsyncClient(
                base_url=f"{pdf_service_url}",
                timeout=180,
                headers={"Connection": "keep-alive"},
                http2=True,
            ) as client:
                response = await client.post("/file_parse", files=files, data=data)
                response.raise_for_status()
                try:
                    ans = response.json().get("results")
                    image_response = ""
                    if ans:
                        for item in ans.get("content_list"):
                            if item and item.get("text"):
                                image_response += item.get("text")
                except Exception:
                    logger.exception(f"{url} 解析图像服务失败:")
            img_stream = io.BytesIO(file_data)
            img_stream.seek(0)
            img_path = f"{knowledge_id}/image/{str(uuid.uuid4())}.jpg"
            write_result = MinIoUtil.min_io_client.put_object(
                "tiance-base",
                img_path,
                img_stream,
                img_stream.getbuffer().nbytes,
                "image/jpg",
            )
            return write_result.object_name, image_response

        # 远程网络地址
        for attempt in range(max_retries):
            try:
                response = requests.get(url, timeout=timeout)
                response.raise_for_status()
                if "image" in response.headers.get("Content-Type", ""):
                    img_stream = io.BytesIO(response.content)
                    # 存入Minio中
                    img_stream.seek(0)
                    img_path = f"{knowledge_id}/image/{str(uuid.uuid4())}.jpg"
                    write_result = MinIoUtil.min_io_client.put_object(
                        "tiance-base",
                        img_path,
                        img_stream,
                        img_stream.getbuffer().nbytes,
                        "image/jpg",
                    )
                    logger.info(f"上传图片成功：{write_result.object_name}")
                    # # 获取图像描述
                    # image_chat = Llm_Service_vllm()
                    # base64_page_image = image_chat.encode_image(img)
                    # image_response = image_chat.answer_question_for_vl(img_prompt, base64_page_image)

                    # 调用解析服务
                    files = [("files", (os.path.basename(url), response.content, "image/jpeg"))]
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
                        "enable_minio": "False",  # 是否启用MinIO
                        "minio_bucket": "tiance-base",
                        # "use_vlm_mode": use_vlm_mode,  # 是否使用vlm模式对图片生成描述
                        # "model_uid": model_uid,  # 模型UID
                        # "api_url": api_url,  # 接口URL
                        # "api_key": api_key,  # 接口密钥
                    }
                    async with httpx.AsyncClient(
                        base_url=f"{pdf_service_url}",
                        timeout=180,
                        headers={"Connection": "keep-alive"},
                        http2=True,
                    ) as client:
                        response = await client.post("/file_parse", files=files, data=data)
                        try:
                            response.raise_for_status()
                            try:
                                ans = response.json().get("results")
                                image_response = ""
                                if ans:
                                    for item in ans.get("content_list"):
                                        if item and item.get("text"):
                                            image_response += item.get("text")
                            except Exception:
                                logger.exception(f"{url} 解析图像服务失败:")
                        except:
                            image_response = ""
                    return write_result.object_name, image_response
                else:
                    raise ValueError("地址不指向图片")
            except (requests.exceptions.RequestException, ValueError) as e:
                logger.exception(f"第{attempt + 1}次失败：{e}")
                if attempt == max_retries + 1:
                    raise
                time.sleep(1)
        return None, None
    except Exception:
        logger.exception(f"上传图像失败: {url}")
        raise


# 所有叶节点的结果


class MarkdownParse:
    def __init__(
        self,
        markdown_text,
        knowledge_id,
        use_vlm_mode,
        model_uid,
        api_url,
        api_key,
        pdf_service_url="http://10.8.21.165:8100",
    ):
        self.ans = []
        md = mistune.create_markdown(renderer=None, plugins=["table"])
        self.ast = md(markdown_text)
        # 解析图片用
        self.knowledge_id = knowledge_id
        self.use_vlm_mode = use_vlm_mode
        self.model_uid = model_uid
        self.api_url = api_url
        self.api_key = api_key
        self.pdf_service_url = pdf_service_url
        assert isinstance(self.ast, list)

    async def run(self):
        for item in self.ast:
            await self.ast_pre_search(item)
        return self.ans

    async def ast_pre_search(self, ast):
        """
        递归先序遍历ast
        """
        try:
            if ast.get("type") == "heading":
                try:
                    level = ast.get("attrs").get("level")
                    maker = "#" * level
                    head_text = maker + " " + ast.get("children")[0].get("raw")
                    self.ans.append(Node("text", None, head_text, None))
                except Exception:
                    pass
                return

            if ast.get("type") == "image":
                try:
                    assert (
                        ast.get("children") is not None
                        and len(ast.get("children")) == 1
                        and ast.get("children")[0].get("children") is None
                    ), "image节点的子节点错误"

                    if ast.get("attrs").get("title"):
                        theme = ast.get("attrs").get("title")
                    elif ast.get("children")[0].get("raw"):
                        theme = ast.get("children")[0].get("raw")
                    else:
                        # 若title和alt均没有，则使用文件名作文theme
                        full_name = os.path.basename(ast.get("attrs").get("url"))
                        theme = full_name.split(".")[0]
                    # 访问链接
                    url = ast.get("attrs").get("url")
                    minio_img_path, image_response = await download_image(
                        url,
                        self.knowledge_id,
                        self.use_vlm_mode,
                        self.model_uid,
                        self.api_url,
                        self.api_key,
                        self.pdf_service_url,
                    )
                    if image_response:
                        self.ans.append(Node("image", minio_img_path, image_response, theme))
                    # else:
                    #     self.ans.append(Node("image", None, url, None))
                except Exception:
                    raise
                return
            if ast.get("type") == "table":
                try:
                    assert ast.get("children") is not None and len(ast.get("children")) == 2, "table节点发生错误"
                    table_head = ast.get("children")[0]
                    table_body = ast.get("children")[1]
                    table_str = ""
                    for head_item in table_head.get("children"):
                        table_str += f"|  {await MarkdownParse.node_pre_search(head_item)}  "
                    table_str += "|\n"
                    for i in range(len(table_head.get("children"))):
                        table_str += "| :-- "
                    table_str += "|\n"
                    for line_item in table_body.get("children"):
                        for table_row in line_item.get("children"):
                            table_str += f"| {await MarkdownParse.node_pre_search(table_row)} "
                        table_str += "|\n"
                    self.ans.append(Node("table", None, table_str, None))
                except Exception:
                    logger.exception(f"解析markdown表格时出错: {ast}")
                    raise
                return
            if ast.get("children") is None:
                if ast.get("type") == "text":
                    # 若是text类型，直接加入
                    self.ans.append(Node("text", None, ast.get("raw"), None))
                elif ast.get("type") == "codespan":
                    # 若是codespan类型，直接加入
                    code_text = "`" + ast.get("raw") + "`"
                    self.ans.append(Node("text", None, code_text, None))
                elif ast.get("type") == "block_code":
                    self.ans.append(Node("text", None, ast.get("raw"), None))
                elif ast.get("type") == "block_html":
                    if ast.get("raw"):
                        my_html = HtmlParse(ast.get("raw"), pdf_service_url=self.pdf_service_url)
                        html_list = await my_html.run()
                        html_text = ""
                        for html in html_list:
                            if html.type == "text":
                                html_text += html.text
                                # 合并text节点，如果超过50个字符，作为一个节点
                                if len(html_text) > 50:
                                    self.ans.append(Node("text", None, html_text, None))
                                    html_text = ""
                            elif html.type == "image":
                                # 如果遇到image节点，把之前text节点和当前image节点加入
                                if html_text:
                                    self.ans.append(Node("text", None, html_text, None))
                                    html_text = ""
                                self.ans.append(html)
                        if html_text:
                            self.ans.append(Node("text", None, html_text, None))
                    # else:
                    #     self.ans.append(Node("html", None, None, None))
                elif ast.get("type") == "inline_html":
                    # 处理内嵌html
                    if ast.get("raw"):
                        my_html = HtmlParse(ast.get("raw"), pdf_service_url=self.pdf_service_url)
                        html_list = await my_html.run()
                        html_text = ""
                        for html in html_list:
                            if html.type == "text":
                                html_text += html.text
                                # 合并text节点，如果超过50个字符，作为一个节点
                                if len(html_text) > 50:
                                    self.ans.append(Node("text", None, html_text, None))
                                    html_text = ""
                            elif html.type in ["image", "table"]:
                                # 如果遇到image节点，把之前text节点和当前image节点加入
                                if html_text:
                                    self.ans.append(Node("text", None, html_text, None))
                                    html_text = ""
                                self.ans.append(html)
                        if html_text:
                            self.ans.append(Node("text", None, html_text, None))
                    # else:
                    #     self.ans.append(Node("html", None, None, None))
            else:
                for child in ast["children"]:
                    await self.ast_pre_search(child)
        except Exception:
            logger.exception(f"解析markdown节点时出错: {ast}")
            raise

    @staticmethod
    async def node_pre_search(ast):
        """
        返回这个子树的先序序列
        """
        if ast.get("children") is None:
            return ast.get("raw")
        start = ""
        for child in ast.get("children"):
            start += await MarkdownParse.node_pre_search(child)
        return start

    async def draw_table(self, ast):
        """
        绘制Markdown形式的表格，上传至Minio
        """
        try:
            assert ast.get("type") == "table", "待绘制节点不是表格节点"
            font = ImageFont.truetype("simsun.ttc", 14)
            table_data = []
            for item in ast.get("children"):
                if item.get("type") == "table_head":
                    one_row = []
                    for col in item.get("children"):
                        one_row.append(await MarkdownParse.node_pre_search(col))
                    table_data.append(one_row)
                elif item.get("type") == "table_body":
                    for row in item.get("children"):
                        one_row = []
                        for col in row.get("children"):
                            one_row.append(await MarkdownParse.node_pre_search(row))
                        table_data.append(one_row)

            # 动态计算尺寸
            col_widths = [max(font.getlength(cell) + 10 for cell in row) for row in table_data]
            row_heights = [max(len(cell.text.split("\n")) * font.size + 10 for cell in row) for row in table_data]

            # 绘制自适应表格
            img = Image.new("RGB", (int(sum(col_widths)), int(sum(row_heights))), "white")
            draw = ImageDraw.Draw(img)
            y = 0
            for row_idx, row in enumerate(table_data):
                x = 0
                for col_idx, cell in enumerate(row):
                    # 绘制单元格背景
                    draw.rectangle(
                        (x, y, x + col_widths[col_idx], y + row_heights[row_idx]), outline="gray", fill="white"
                    )
                    # 居中绘制文本
                    text_width = font.getlength(cell)
                    text_x = x + (col_widths[col_idx] - text_width) / 2
                    text_y = y + 10
                    draw.text((text_x, text_y), cell, font=font, fill="black")
                    x += col_widths[col_idx]
                y += row_heights[row_idx]

            # 上传到远程
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            buffer.seek(0)
            img_path = f"multimode/{str(uuid.uuid4())}.jpg"
            write_result = MinIoUtil.min_io_client.put_object(
                "tiance-base", img_path, buffer, buffer.getbuffer().nbytes, "image/jpg"
            )
            return write_result.object_name
        except Exception:
            logger.exception(f"绘制markdown表格时出错: {ast}")
            raise


class HtmlParse:
    def __init__(
        self,
        html_text,
        knowledge_id=None,
        use_vlm_mode=None,
        model_uid=None,
        api_url=None,
        api_key=None,
        pdf_service_url="http://10.8.21.165:8100",
    ):
        self.soup = BeautifulSoup(html_text, "lxml")
        self.ans = []
        # 临时存放表格的标题，这同一个HtmlParse只能处理一个表格
        self.table_theme = ""
        # 临时存放表格的
        self.table_ans = ""
        # 临时存放当前表格的坐标
        self.co = [1, 1]
        # 临时存放跨越多行或者多列的数据，以重复使用
        self.du = {}
        # 临时存放纯文本，纯文本缓存，若缓存大于15则成一个节点
        self.pure_text = ""
        # 解析图片用
        self.knowledge_id = knowledge_id
        self.use_vlm_mode = use_vlm_mode
        self.model_uid = model_uid
        self.api_url = api_url
        self.api_key = api_key
        self.pdf_service_url = pdf_service_url

    async def run(self):
        await self.html_parser(self.soup)
        return self.ans

    async def html_parser(self, ast):
        """
        递归解析html文件
        :param ast:
        :return:
        """
        try:
            if hasattr(ast, "contents"):
                if ast.name in ["img", "video", "table", "audio", "h1", "h2", "h3", "h4", "h5", "h6"]:
                    # 需要单独处理,先处理纯文本缓存
                    if self.pure_text:
                        self.ans.append(Node("text", None, self.pure_text, None))
                        self.pure_text = ""
                    if ast.name == "img":
                        if ast.attrs.get("src") is not None:
                            minio_img_path, image_response = await download_image(
                                ast.attrs.get("src"),
                                self.knowledge_id,
                                self.use_vlm_mode,
                                self.model_uid,
                                self.api_url,
                                self.api_key,
                                self.pdf_service_url,
                            )
                            if image_response:
                                theme = ast.attrs.get("title") if ast.attrs.get("title") else ast.attrs.get("alt")
                                self.ans.append(Node("image", minio_img_path, image_response, theme))
                            # else:
                            #     self.ans.append(Node("image", None, ast.attrs.get("src"), None))
                    elif ast.name == "video":
                        if ast.attrs.get("poster") is not None:
                            minio_img_path, image_response = await download_image(
                                ast.attrs.get("poster"),
                                self.knowledge_id,
                                self.use_vlm_mode,
                                self.model_uid,
                                self.api_url,
                                self.api_key,
                                self.pdf_service_url,
                            )
                            if image_response:
                                theme = ast.attrs.get("title") if ast.attrs.get("title") else ast.attrs.get("alt")
                                self.ans.append(Node("image", minio_img_path, image_response, theme))
                            else:
                                self.ans.append(Node("image", None, ast.attrs.get("poster"), None))
                    elif ast.name == "table":
                        self.du = {}
                        self.table_ans = ""
                        self.co = [1, 1]
                        self.table_theme = ""
                        await self.handle_html_table(ast)
                        if not self.table_theme:
                            self.table_theme = None
                        table_file_path = await self.draw_table(ast)
                        self.ans.append(Node("table", table_file_path, self.table_ans, self.table_theme))
                    elif ast.name == "audio":
                        # 不处理音频
                        self.ans.append(Node("audio", None, ast.attrs.get("src"), None))
                    elif ast.name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                        head_text = "#" * int(ast.name[1]) + " " + ast.text
                        self.ans.append(Node("text", None, head_text, None))
                # 遍历子节点
                else:
                    for item in ast.contents:
                        await self.html_parser(item)
            else:
                # 没有contents一定是纯文本
                if ast.text:
                    node_text = str(ast.text).strip()
                    if node_text:
                        if len(self.pure_text + node_text) > 20:
                            if self.pure_text:
                                self.ans.append(Node("text", None, self.pure_text, None))
                            self.pure_text = node_text
                            if len(self.pure_text) > 20:
                                self.ans.append(Node("text", None, self.pure_text, None))
                                self.pure_text = ""
                        else:
                            self.pure_text += node_text

        except Exception:
            logger.exception(f"解析html节点时出错: {ast}")
            raise

    async def handle_html_table(self, ast):
        # 递归处理html格式的table，传进来的是Tag格式
        if not hasattr(ast, "contents"):
            return
        if ast.name == "caption":
            self.table_theme = ast.text
        for row_entity in ast.contents:
            # 如果子节点是叶节点，则跳过
            if not hasattr(row_entity, "contents"):
                continue
            # 如果子节点不是叶节点，且不是tr节点，则往下伸长。
            if row_entity.name != "tr":
                await self.handle_html_table(row_entity)
            # 如果是tr节点，则处理
            else:
                for row_item in row_entity.contents:
                    if not (hasattr(row_item, "contents") and row_item.name in ["th", "td"]):
                        continue
                    while self.du.get((self.co[0], self.co[1])):
                        self.table_ans += f"|  {self.du.get((self.co[0], self.co[1]))}  "
                        self.co[1] += 1
                    self.table_ans += f"|  {row_item.text.strip()}  "
                    if row_item.attrs and (row_item.attrs.get("rowspan") or row_item.attrs.get("colspan")):
                        row_num = int(row_item.attrs.get("rowspan")) if row_item.attrs.get("rowspan") else 1
                        col_num = int(row_item.attrs.get("colspan")) if row_item.attrs.get("colspan") else 1
                        for i in range(row_num):
                            for j in range(col_num):
                                self.du[(self.co[0] + i, self.co[1] + j)] = row_item.text.strip()
                    self.co[1] += 1
                self.table_ans += "|\n"
                if self.co[0] == 1:
                    for i in range(self.co[1] - 1):
                        self.table_ans += "| :-- "
                    self.table_ans += "|\n"
                self.co[0] += 1
                self.co[1] = 1

    async def draw_table(self, ast):
        """
        将html格式的表格绘画为图像。
        """
        try:
            assert ast.name == "table", "待绘画的节点不是表格节点"
            font = ImageFont.truetype("simsun.ttc", 14)

            # 动态计算尺寸
            col_widths = [
                max(font.getlength(cell.text) + 20 for cell in row.select("td,th")) for row in ast.find_all("tr")
            ]
            row_heights = [
                max(len(cell.text.split("\n")) * font.size + 20 for cell in row.select("td,th"))
                for row in ast.find_all("tr")
            ]

            # 绘制自适应表格
            img = Image.new("RGB", (int(sum(col_widths)), int(sum(row_heights))), "white")
            draw = ImageDraw.Draw(img)
            y = 0
            for row_idx, row in enumerate(ast.find_all("tr")):
                x = 0
                for col_idx, cell in enumerate(row.find_all(["td", "th"])):
                    # 绘制单元格背景（可选）
                    draw.rectangle(
                        (x, y, x + col_widths[col_idx], y + row_heights[row_idx]), outline="gray", fill="white"
                    )
                    # 居中绘制文本
                    text = cell.get_text()
                    text_width = font.getlength(text)
                    text_x = x + (col_widths[col_idx] - text_width) / 2
                    text_y = y + 10
                    draw.text((text_x, text_y), text, font=font, fill="black")
                    x += col_widths[col_idx]
                y += row_heights[row_idx]
            logger.info("->绘画表格完毕")
            # 上传到远程
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG")
            buffer.seek(0)
            img_path = f"{self.knowledge_id}/table/{str(uuid.uuid4())}.jpg"
            write_result = MinIoUtil.min_io_client.put_object(
                "tiance-base", img_path, buffer, buffer.getbuffer().nbytes, "image/jpg"
            )
            logger.info(f"->上传表格完毕：{write_result.object_name}")
            return write_result.object_name
        except Exception as e:
            logger.error("绘画与上传表格失败", exc_info=True)
            return None


async def fun1():
    mime_type = "image/jpeg"
    # file_path = "D:\Pictures\zly.jpg"
    file_path = "http://10.8.21.164:8082/logo.png"
    # with open(file_path, "rb") as f:
    #     f_bytes = f.read()

    response = requests.get(file_path, timeout=5)
    response.raise_for_status()
    if "image" in response.headers.get("Content-Type", ""):
        img_stream = io.BytesIO(response.content)

    files = [("files", (os.path.basename(file_path), response.content, mime_type))]
    data = {
        "output_dir": "./output",  # 输出目录
        "backend": "pipeline",  # 后端
        "parse_method": "auto",  # 解析方法
        "formula_enable": "false",  # 公式
        "table_enable": "false",  # 表格
        "server_url": "",  # 服务URL
        "return_md": "false",  # 返回MD
        "return_middle_json": "false",  # 返回中间JSON
        "return_model_output": "false",  # 返回模型输出
        "return_content_list": "true",  # 返回内容列表
        "return_images": "false",  # 返回图像
        "start_page_id": "0",  # 开始页ID
        "end_page_id": "99999",  # 结束页ID
        "enable_minio": "False",  # 是否启用MinIO
        "minio_bucket": "tiance-base",
    }

    async with httpx.AsyncClient(
        base_url="http://10.8.21.165:8100",
        timeout=300,
        headers={"Connection": "keep-alive"},
        http2=True,
    ) as client:
        response = await client.post("/file_parse", files=files, data=data)
        response.raise_for_status()
        try:
            return response.json()
        except Exception as e:
            logger.error(f"解析PDF服务返回的JSON失败: {str(e)}，原始内容: {response.content}", exc_info=True)
            raise Exception("远程PDF服务返回内容不是有效的JSON格式")


if __name__ == "__main__":
    a = BasicParser()
    # ans = asyncio.run(a.parse("D:\\tianyan\\tiance-base\\variant.html"))
    # ans = asyncio.run(a.parse("D:\\tianyan\\tiance-base\\agent.md"))
    ans = asyncio.run(a.parse("D:\\tianyan\\tiance-base\\variant.md"))
    # b = asyncio.run(fun1())

    pass
