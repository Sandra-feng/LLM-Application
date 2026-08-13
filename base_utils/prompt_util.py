#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base 
@File    ：prompt_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:22 
"""


class PromptUtil(object):
    """
    提示词工具类
    """

    @staticmethod
    def format_prompt(prompt):
        """
        格式化提示词-清除前后空格，对齐所有行
        :param prompt: 提示词
        :return:
        """
        new_line_list = list()
        line_list = prompt.split("\n")
        for i in range(len(line_list)):
            new_line = line_list[i].strip()
            if new_line != "":
                new_line_list.append(new_line)
            else:
                if i == 0 or i == len(line_list) - 1:
                    continue
                else:
                    new_line_list.append(new_line)
        return "\n".join(new_line_list)
