#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base 
@File    ：excel_util.py.py
@Author  ：TaoMeng
@Date    ：2024/8/25 20:33 
"""
import xlrd
import pandas as pd


class ExcelUtil(object):
    """
    excel工具类
    """

    @staticmethod
    def to_list(excel_data, sheet_name, start_col=0):
        """
        通过sheet_name索引表格数据,并将其转换为列表格式
        :param excel_data: excel数据
        :param sheet_name: sheet name
        :param start_col: 列的起始索引,1表示仅保留第一列之后的列数据,0表示保留所有列的列数据
        :return: list
        """
        store = []
        table = excel_data.sheet_by_name(sheet_name=sheet_name)
        rows = table.nrows
        for row in range(rows):
            row_values = table.row_values(rowx=row)
            store.append(row_values[start_col:])
        return store

    @staticmethod
    def to_df(excel_data, sheet_name, start_col=0, is_headers=True):
        """
        将指定的sheet_name转换为DataFrame格式
        :param excel_data: excel数据
        :param sheet_name: sheet name
        :param start_col: 列的起始索引
        :param is_headers: 是否保留sheet的第一行作为headers
        :return: DataFrame
        """
        store = ExcelUtil.to_list(excel_data=excel_data, sheet_name=sheet_name, start_col=start_col)
        if store:
            if is_headers:
                return pd.DataFrame(data=store[1:], columns=store[0])
            else:
                return pd.DataFrame(data=store, columns=[col_name for col_name in range(len(store[-1]))])
        else:
            return None

    @staticmethod
    def read_excel(file_path, sheet_name):
        """
        读取excel文件
        :param file_path:文件路径
        :param sheet_name: 表格名称
        :return:
        """
        data = xlrd.open_workbook(file_path)
        df = ExcelUtil.to_df(excel_data=data, sheet_name=sheet_name)
        return df


if __name__ == '__main__':
    # excel文件路径
    excel_file = 'C:/Users/Administrator/Desktop/compute_template.xlsx'
    data_df = ExcelUtil.read_excel(excel_file, sheet_name='模板')
    for i in (range(data_df.shape[0])):
        company = data_df['痰湿'][i]
        print(company)
