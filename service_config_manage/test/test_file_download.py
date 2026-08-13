#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：test_file_download.py
@Author  ：YunPeng
@Date    ：2024/8/29 14.51
"""
import sys
import requests
from test_config import ROUTE

if __name__ == "__main__":
    url = f"{ROUTE}/download_file"

    # 文件名和文件URL作为查询参数
    file_name = "Table_of_Contents.pdf"
    file_url = "http://192.168.33.142:9000/tiance-base/pytest/Table_of_Contents.pdf?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=tansun%2F20240829%2Fus-east-1%2Fs3%2Faws4_request&X-Amz-Date=20240829T020349Z&X-Amz-Expires=604800&X-Amz-SignedHeaders=host&X-Amz-Signature=9651cf02c4706681d434be54d405001fff39cff210703f9597b04d65fdbe8049"

    # 构建查询字符串
    params = {
        "file_name": file_name,
        "file_url": file_url
    }

    # 发送 GET 请求
    response = requests.get(url, params=params)

    # 检查响应状态码
    if response.status_code == 200:
        # 保存下载的文件
        with open(file_name, "wb") as file:
            file.write(response.content)
        print(f"文件下载成功并保存为 {file_name}")
    else:
        print(f"文件下载失败，状态码: {response.status_code}, 响应内容: {response.text}")
