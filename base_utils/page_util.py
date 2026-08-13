#!/usr/bin/env python
# -*- encoding: utf-8 -*-
'''
@File         :list_util.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/03 09:50:30
'''

class PageUtil(object):
    """
    分页工具类
    """

    @staticmethod
    def paginate_list(data: list, page: int, page_size: int):
        total = len(data)
        result = {"total": 0, "result": []}
        if total == 0:
            return result
        start_index = (page - 1) * page_size
        end_index = start_index + page_size
        result["total"] = total
        result["result"] = data[start_index:end_index]
        return result