#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：ret_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:24
"""
from typing import Union
from fastapi.responses import JSONResponse, Response


class RetUtil(object):
    """
    结果出来工具类
    """
    success_code = '0000'
    error_code = '0001'
    header_fail_code = '0002'
    auth_fail_code = '0003'
    token_invalid_code = '0004'
    body_fail_code = '0005'

    @staticmethod
    def response_ok(data: Union[list, dict, str]) -> Response:
        """
        接口：返回正常
        :param data: 结果数据
        :return:
        """
        return JSONResponse({"status": True, "message": "success", 'data': data})

    @staticmethod
    def response_error(code: str,message: str = ''):
        """
        接口：返回错误
        :param message: 错误信息
        :return:
        """
        return {"code": code,"msg": message,"status": False,}

    @staticmethod
    def response_stream(data: Union[list, dict, str]):
        """
        接口：返回流
        :param data: token数据
        :return:
        """
        return {"status": True, "message": "success", 'content': data}