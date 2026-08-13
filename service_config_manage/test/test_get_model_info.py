#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：test_get_model_info.py
@Author  ：YunPeng
@Date    ：2024/8/29 14.51
"""

import requests
from test_config import ROUTE


def test_get_model_info(url):
    response = requests.post(url)
    response_data = response.json()
    print(response_data)


if __name__ == "__main__":
    url = f"{ROUTE}/get_model_size"
    test_get_model_info(url=url)
