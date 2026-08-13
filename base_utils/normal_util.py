import hashlib
import re

def quick_sort(li, start, end, index):
    """ 排序"""
    if start >= end:
        return
    low = start
    hight = end
    mid = li[low][index]
    mid_all = li[low]
    while low < hight:
        while low < hight and li[hight][index] < mid:  # <
            hight -= 1
        li[low] = li[hight]
        while low < hight and li[low][index] >= mid:  # >=
            low += 1
        li[hight] = li[low]
    li[low] = mid_all
    quick_sort(li, start, low - 1, index)
    quick_sort(li, low + 1, end, index)


def md5(arg):
    # 将数据转换成UTF-8格式
    se = hashlib.md5(arg.encode('utf-8'))
    # 将hash中的数据转换成只包含十六进制的数字
    result = se.hexdigest()
    return result

def contains_chinese(text):
    # 中文字符的 Unicode 范围
    pattern = re.compile(r'[\u4e00-\u9fff]+')
    return bool(pattern.search(text))