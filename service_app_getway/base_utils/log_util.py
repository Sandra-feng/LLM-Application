#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：log_util.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:30
"""

import json
from loguru import logger
class LogUtil:
    """
    日志工具类（兼容层）。交由全局 logging 配置处理。
    """

    _logger = None

    @staticmethod
    def init(process_name: str):
        if LogUtil._logger is not None:
            LogUtil._logger.info("Logger already initialized, skipping reconfiguration.")
            return
# logger = loguru logger (auto-migrated)
        logger.propagate = True
        LogUtil._logger = logger
        LogUtil._logger.info(f"Logger for '{process_name}' initialized.")

    @staticmethod
    def _get_logger():
        if LogUtil._logger is None:
            raise RuntimeError("LogUtil has not been initialized. Call LogUtil.init() first.")
        return LogUtil._logger

    @staticmethod
    def info(msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().info(str(msg).replace("\n", "\\n"), *args, **kwargs)

    @staticmethod
    def error(msg, *args, exc_info=False, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().error(str(msg), *args, exc_info=exc_info, **kwargs)

    @staticmethod
    def exception(msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().exception(str(msg), *args, **kwargs)

    @staticmethod
    def debug(msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().debug(str(msg).replace("\n", "\\n"), *args, **kwargs)

    @staticmethod
    def warning(msg, *args, **kwargs):
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().warning(str(msg), *args, **kwargs)

    # 兼容旧方法名
    warn = warning

    @staticmethod
    def log_json(describe, **kwargs):
        msg = "{0}: {1}".format(
            describe, json.dumps(kwargs.get("kwargs") if "kwargs" in kwargs else kwargs, ensure_ascii=False)
        )
        LogUtil._get_logger().info(msg.replace("\n", "\\n"), stacklevel=2)


if __name__ == "__main__":
    LogUtil.init(process_name="chat-agent")
    args_dict = {
        "debug": True,
        "level": logging.DEBUG,
        "name": "chat-agent",
        "meta_info": {"host": "localhost", "port": 1208},
    }
    hh = [{"host": "localhost", "port": 1208}, {"host": "localhost", "port": 1208}]
    LogUtil.log_json(describe="-> 进行测试", kwargs=args_dict)
    LogUtil.log_json(describe="-> 进行测试", messages=hh)
