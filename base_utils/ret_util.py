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

    @staticmethod
    def response_ok(data: Union[list, dict, str, None]) -> Response:
        """
        接口：返回正常
        :param data: 结果数据
        :return:
        """
        return JSONResponse({"code":200, "status": True, "message": "success", "data": data})

    @staticmethod
    def response_error(code: int=500, message: str = "", data: Union[list, dict, str] = "") -> JSONResponse:
        """
        接口：返回错误
        :param message: 错误信息
        :param data: 与错误相关的数据
        :return: JSONResponse
        """
        return JSONResponse({"code":code,"status": False, "message": message, "data": data})

    @staticmethod
    def response_stream(data: Union[list, dict, str]):
        """
        接口：返回流
        :param data: token数据
        :return:
        """
        return {"status": True, "message": "success", "data": data}

    @staticmethod
    def return_error(message: str = "") -> dict:
        """
        方法：返回错误
        :param message: 错误信息
        :return:
        """
        return {"status": False, "message": message}

    @staticmethod
    def return_ok(data: Union[list, dict, str]) -> dict:
        """
        方法：返回正常
        :param data: 返回结果
        :return:
        """
        return {"status": True, "data": data}

    @staticmethod
    def get_status(ret):
        """
        获取状态
        :param ret: 结果
        :return:
        """
        return ret.get("status", False)

    @staticmethod
    def get_message(ret):
        """
        获取消息
        :param ret: 结果
        :return:
        """
        return ret.get("message", "")

    @staticmethod
    def get_data(ret):
        """
        获取数据
        :param ret: 结果
        :return:
        """
        return ret.get("data", "")
