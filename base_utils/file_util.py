#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base 
@File    ：file_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:19 
"""
import os
import json
import shutil
from pathlib import Path


class FileUtil(object):
    """
    文件工具类
    """

    @staticmethod
    def get_parent_path(current_path):
        """
        获取上一级目录
        :param current_path: 当前目录
        :return:
        """
        cur_path = Path(current_path)
        parent_path = str(cur_path.parent)
        parent_path = parent_path.replace("\\", "/")
        return parent_path

    @staticmethod
    def get_file_name(file_path):
        """
        获取文件名称-不包含后缀
        :param file_path: 文件路径
        :return:
        """
        cur_path = Path(file_path)
        return cur_path.stem

    @staticmethod
    def get_file_full_name(file_path):
        """
        获取文件名全称-包含文件后缀
        :param file_path: 文件路径
        :return:
        """
        cur_path = Path(file_path)
        return cur_path.name

    @staticmethod
    def get_file_suffix_name(file_path):
        """
        获取文件后缀名称
        :param file_path: 文件路径
        :return:
        """
        cur_path = Path(file_path)
        return cur_path.suffix

    @staticmethod
    def get_superior_path(current_path):
        """
        获取上两级目录
        :param current_path: 当前目录
        :return:
        """
        cur_path = Path(current_path)
        superior_path = str(cur_path.parent.parent)
        superior_path = superior_path.replace("\\", "/")
        return superior_path

    @staticmethod
    def create_path(current_path):
        """
        创建目录
        :param current_path: 当前目录
        :return:
        """
        if not os.path.exists(current_path):
            os.makedirs(current_path)

    @staticmethod
    def load_json_file(file_path, mode='r', encoding='utf-8'):
        """
        读取json文件内容
        :param file_path:文件路径
        :param mode:读取方式
        :param encoding:编码
        :return:
        """
        with open(file_path, mode=mode, encoding=encoding) as f:
            return json.load(f)

    @staticmethod
    def save_json_file(file_path, json_content):
        """
        保存json文件
        :param file_path: json文件路径
        :param json_content: json内容
        :return:
        """
        with open(file_path, 'w') as f:
            json.dump(json_content, f)

    @staticmethod
    def del_file_list(file_list):
        """
        删除文件列表
        :param file_list: 文件列表
        :return:
        """
        # 删除文件
        for f in file_list:
            if os.path.exists(f):
                os.remove(f)

    @staticmethod
    def del_one_file(file_path):
        """
        删除文件列表
        :param file_path: 文件列表
        :return:
        """
        # 删除文件
        if os.path.exists(file_path):
            os.remove(file_path)

    @staticmethod
    def load_file_content(file_path, mode='r', encoding='utf-8'):
        """
        按行读取文件内容
        :param file_path:文件内容
        :param mode:读取方式
        :param encoding:编码
        :return:
        """
        file = open(file_path, mode=mode, encoding=encoding)
        lines = []
        for line in file.readlines():
            lines.append(line.strip())
        file.close()
        return lines

    @staticmethod
    def get_file_path(file_path, file_formats=['xml', 'bmp', 'jpg', 'jpeg', 'png', 'tif', 'tiff', 'dng']):
        """
        功能说明： 获取文件夹下面，指定格式文件的路径（多级迭代遍历），并返回
        :param file_path:  文件根路径
        :param file_formats:  文件格式
        :return:
        """
        file_list = []
        ff = os.walk(file_path)
        for root, dirs, files in ff:
            for file in files:
                if os.path.splitext(file)[-1].replace(".", "") in file_formats:
                    file_list.append(os.path.join(root, file))
        return file_list

    @staticmethod
    def get_file_name_path(file_path, file_formats=['xml', 'bmp', 'jpg', 'jpeg', 'png', 'tif', 'tiff', 'dng']):
        """
        功能说明： 获取文件夹下面，指定格式文件的路径（多级迭代遍历），并返回
        :param file_path:  文件根路径
        :param file_formats:  文件格式
        :return:
        """
        file_list = []
        ff = os.walk(file_path)
        for root, dirs, files in ff:
            for file in files:
                if os.path.splitext(file)[-1].replace(".", "") in file_formats:
                    file_split = file.split("_")
                    file_new = file_split[0] + "_" + file_split[1] + "_" + file_split[2]  # 特殊情况处理
                    if file_new not in file_list:
                        file_list.append(file_new)
        return file_list

    @staticmethod
    def del_invalid_dir(path):
        """
        删除目录
        :param path:
        :return:
        """
        if os.path.exists(path):
            # os.removedirs(path)
            print(path)
            shutil.rmtree(path)


if __name__ == '__main__':
    s = FileUtil.get_file_suffix_name("/jiu_ti/体质问答6.28.docx")
    print(s)
