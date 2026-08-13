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
    日志工具类（兼容层）。
    统一交由全局 logging 配置控制，此处不再创建 handler，避免重复与冲突。
    """

    _logger = None

    @staticmethod
    def init(process_name: str, log_to_console: bool = True):
        """
        兼容旧接口：初始化命名 logger，但不再新增任何 handler；
        全局配置由 `observability.logging_config.setup_logging_from_env` 负责。
        """
        if LogUtil._logger is not None:
            LogUtil._logger.info("Logger already initialized, skipping reconfiguration.")
            return
# logger = loguru logger (auto-migrated)
        logger.propagate = True  # 交给根 logger 处理
        LogUtil._logger = logger
        LogUtil._logger.info(f"Logger for '{process_name}' initialized.")

    @staticmethod
    def _get_logger():
        """内部方法，获取logger实例，如果未初始化则抛出异常。"""
        if LogUtil._logger is None:
            raise RuntimeError(
                "LogUtil has not been initialized. Please call LogUtil.init() at the start of your application."
            )
        return LogUtil._logger

    @staticmethod
    def info(msg, *args, **kwargs):
        """
        记录 INFO 级别日志。
        """
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().info(str(msg).replace("\n", "\\n"), *args, **kwargs)

    @staticmethod
    def error(msg, *args, exc_info=False, **kwargs):
        """
        记录 ERROR 级别日志。
        :param exc_info: 如果为 True, 则自动附加异常信息。
        """
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().error(str(msg), *args, exc_info=exc_info, **kwargs)

    @staticmethod
    def exception(msg, *args, **kwargs):
        """
        记录 ERROR 级别日志并自动附加异常堆栈信息。
        此方法应在 except 块中调用。
        """
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().exception(str(msg), *args, **kwargs)

    @staticmethod
    def debug(msg, *args, **kwargs):
        """
        调试日志
        :param msg: 需要记录的信息
        """
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().debug(str(msg).replace("\n", "\\n"), *args, **kwargs)

    @staticmethod
    def warning(msg, *args, **kwargs):
        """
        警告日志
        :param msg: 需要记录的信息
        """
        kwargs.setdefault("stacklevel", 2)
        LogUtil._get_logger().warning(str(msg), *args, **kwargs)

    # 兼容旧方法名
    warn = warning

    @staticmethod
    def log_json(describe, **kwargs):
        """
        记录json格式
        :param describe: 说明
        :param kwargs: 参数信息
        :return:
        """
        msg = "{0}: {1}".format(
            describe, json.dumps(kwargs.get("kwargs") if "kwargs" in kwargs else kwargs, ensure_ascii=False)
        )
        # stacklevel=2 to show correct caller
        LogUtil._get_logger().info(msg.replace("\n", "\\n"), stacklevel=2)


if __name__ == "__main__":
    # 初始化日志，默认会输出到控制台
    LogUtil.init(process_name="chat-agent-test")

    # 再次调用init，会跳过配置，不会重复记录
    LogUtil.init(process_name="chat-agent-test")

    LogUtil.info("这是一条普通信息日志。")
    LogUtil.warn("这是一条警告日志。")
    LogUtil.debug("这是一条调试日志。")

    try:
        1 / 0
    except ZeroDivisionError:
        # 使用 exception() 方法可以在except块中自动记录完整的错误堆栈信息
        LogUtil.exception("计算出错！")

    # 使用 log_json 记录结构化数据
    user_data = {"user_id": "007", "action": "login", "status": "success"}
    LogUtil.log_json("用户操作记录", **user_data)
