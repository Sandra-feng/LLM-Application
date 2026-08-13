#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：time_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:33
"""
import re
import time
from datetime import datetime, timezone


class TimeUtil(object):
    """
    时间工具类
    """

    @staticmethod
    def date_to_timestamp(date=None, format_string="%Y-%m-%d %H:%M:%S"):
        """
        将时间字符串转换为13位时间戳
        :param date: 时间字符串默认为2017-10-01 13:37:04格式 | (str)
        :param format_string: (str)
        :return:
        """
        if isinstance(date, str):
            return int(time.mktime(time.strptime(date, format_string)) * 1000)
        if isinstance(date, datetime):
            return int(time.mktime(time.strptime(date.strftime(format_string), format_string)) * 1000)

    @staticmethod
    def timestamp_to_date(stamp, format_string="%Y-%m-%d %H:%M:%S", type="string"):
        """
        将时间戳转换为指定格式的字符串
        :param stamp: 时间戳 float
        :param format_string: str
        :param type: 'string'|'datetime' 限制返回的时间类型
        :return: str | datetime
        """
        if type == "string":
            return time.strftime(format_string, time.localtime(stamp))
        else:
            return datetime.fromtimestamp(stamp, tz=timezone.utc)

    @staticmethod
    def current_timestamp():
        """
        当前时间戳
        :return:
        """
        return int(time.time() * 1000)

    @staticmethod
    def get_current_format_time():
        """
        获取当前时间
        :return:
        """
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))

    @staticmethod
    def timestamp_to_day_timestamp(timestamp=None):
        """
        转换为天的时间戳
        :param timestamp:
        :return:
        """
        return datetime.fromtimestamp(timestamp / 1000)


if __name__ == "__main__":
    # 测试，获取当前时间
    print(TimeUtil.get_current_format_time())
    print(TimeUtil.date_to_timestamp("2024-08-28 21:52:22"))
    print(TimeUtil.timestamp_to_date(1724853142000))
