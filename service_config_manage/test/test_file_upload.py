#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：test_file_upload.py
@Author  ：YunPeng
@Date    ：2024/8/29 14.51
"""
import sys
import json
sys.path.append("././")
import requests
from test_config import ROUTE


def test_model_launch_api(url, files, data):
    response = requests.post(url, files=files, data=data)
    print(response.content)


if __name__ == "__main__":
    url = f"{ROUTE}/upload_file"

    # 定义文件信息
    file_name = "Table_of_Contents.pdf"
    file_name1 = "jianli.png"
    file_type = "pdf"
    file_type1 = "png"
    file_path = r"D:\Table_of_Contents.pdf"
    file_path1 = r"D:\彭雲\桌面\1.png"

    # 打开文件并准备上传
    with open(file_path, "rb") as file, open(file_path1, "rb") as file1:
        # 准备文件数据和其他参数
        files = [
            ("files", (file_name, file)),
            ("files", (file_name1, file1))
        ]
        # 将 file_names 和 file_types 作为普通字符串，逗号分隔传递
        data = {
            "file_names": f"{file_name},{file_name1}",
            "file_types": f"{file_type},{file_type1}"
        }

        # 发送 POST 请求
        response = requests.post(url, files=files, data=data)

        # 检查响应状态码
        if response.status_code == 200:
            print("文件上传成功")
            print("响应内容:", response.json())
        else:
            print(f"文件上传失败，状态码: {response.status_code}, 响应内容: {response.text}")
