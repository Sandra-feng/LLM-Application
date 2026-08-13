#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base 
@File    ：number_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 22:08 
"""


class NumberUtil:
    """
    数字工具类
    """

    def __init__(self):
        pass

    @staticmethod
    def __is_legal_float_numbers(s):
        """
        字符串是否是一个float
        :param s: 字符串
        :return:
        """
        try:
            float(s)
        except ValueError:
            return False
        else:
            return True

