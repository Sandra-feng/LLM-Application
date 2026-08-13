#!/usr/bin/env python
# -*- encoding: utf-8 -*-
"""
@File         : file_progress.py
@Description  : 文档解析与切片入库，存入进度
@Author       : tanxinji
@Date         : 2025/06/26
"""
import time
import traceback

from base_utils.log_util import LogUtil
from base_utils.mongodb_util import MongodbUtil

from loguru import logger
# logger = loguru logger (auto-migrated)
collection_name = "upload_file_progress"


# logger = loguru logger (auto-migrated)
def set_progress(file_id: str, status: str, progress: float, now_time: float):
    """
    文件解析与入库的进度设置吗，设置时，必须要先设置起始点，即进度为零的时间
    file_id: 文件id，作为该表的唯一id
    status: 需要更新的状态
    progress: 该状态的进度
    """
    try:
        result = MongodbUtil.query_doc_by_id(collection_name, file_id)
        if result is None:
            # 添加一条新数据
            add_value = {"_id": file_id, "0": 0.0, "1": 0.0, "2": 0.0, "3": 0.0,
                         status: progress, f"{status}_start_time": now_time}
            MongodbUtil.insert_one(collection_name, add_value)
            return {"_id": file_id, status: progress}

        if result.get(status, 0.0) >= 100.0:
            return {"_id": file_id, status: progress}

        start_time = result.get(f"{status}_start_time", 0)
        if start_time == 0:
            MongodbUtil.update_docs_by_condition(collection_name,
                                                 {'_id': file_id},
                                                 replace_data={
                                                     "$set": {status: progress, f"{status}_start_time": now_time}})
        else:
            MongodbUtil.update_docs_by_condition(collection_name,
                                                 {'_id': file_id},
                                                 replace_data={
                                                     "$set": {status: progress, f"{status}_time": now_time - start_time}})
        return {"_id": file_id, status: progress}
    except Exception as e:
        logger.error(msg=f"设置文件解析与入库进度时出错", exc_info=True)
        raise


def get_progress(file_id: str):
    """
    同步方法：获取文件处理全流程进度（包含4个阶段）
    返回格式与之前定义完全一致
    """
    try:
        result = MongodbUtil.query_doc_by_id(collection_name, file_id)
        assert result is not None, "查询不到进度信息"

        stages = {
            "0": {"name": "内容提取", "progress": 0, "time_spent": 0},
            "1": {"name": "文档分块", "progress": 0, "time_spent": 0},
            "2": {"name": "向量嵌入", "progress": 0, "time_spent": 0},
            "3": {"name": "索引构建", "progress": 0, "time_spent": 0}
        }

        for stage_id in stages.keys():
            progress = result.get(stage_id, 0)
            stages[stage_id]["progress"] = round(progress, 4)
            stages[stage_id]["time_spent"] = round(result.get(f"{stage_id}_time", 0), 4)
            stages[stage_id]["is_start"] = True if result.get(f"{stage_id}_start_time", False) else False

        current_stage = None
        for stage_id in sorted(stages.keys()):
            if stages[stage_id]["is_start"]:
                current_stage = stage_id
                break

        total_progress = sum(s["progress"] for s in stages.values()) / 4
        total_time = sum(s["time_spent"] for s in stages.values())

        return {
            "stages": stages,
            "current_stage": current_stage,
            "current_stage_name": None if current_stage is None else stages[current_stage]["name"],
            "total_progress": round(total_progress, 4),
            "total_time": round(total_time, 4)
        }
    except Exception as e:
        raise