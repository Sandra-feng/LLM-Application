#!/usr/bin/env python
"""
@File         :launch_service.py
@Description  :
@Author       :QiangQu
@Date         :2024/09/02 09:47:38
"""

import copy

import requests
from bson import ObjectId
from loguru import logger

from base_configs.api_config import ApiConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.ret_util import RetUtil
from base_utils.time_util import TimeUtil


# logger = loguru logger (auto-migrated)
class LaunchService:
    @staticmethod
    async def llm_model_launch(params_dict: dict):
        """
        启动llm大模型
        """
        try:
            if isinstance(params_dict.get("gpu_idx"), list):
                params_dict["gpu_idx"] = list(map(int, params_dict.get("gpu_idx")))
            # 转换为xinference对应参数键值对
            payload = copy.deepcopy(params_dict)
            payload.pop("is_think")
            payload.pop("modalities")
            payload.pop("is_realtime")
            payload["model_name"] = payload.pop("model_id")
            # 是否在GPU上运行
            if payload.get("device") == "GPU":
                logger.info("->在GPU上运行")
                payload.pop("device")
                payload["n_gpu"] = "auto"
            else:
                payload.pop("device")
                payload["n_gpu"] = None

            # 转换为xinference的lora适配参数
            if "lora_list" in payload and payload.get("lora_list"):
                payload["peft_model_config"] = payload.pop("lora_list")
            else:
                payload.pop("lora_list")
            # 转换为payload下的键值对
            if "model_engine_params" in payload:
                # if "gpu_memory_utilization" in payload['model_engine_params'].keys():
                # payload['model_engine_params']['gpu_memory_utilization']=float(payload['model_engine_params']['gpu_memory_utilization'])
                payload.update(payload.pop("model_engine_params"))

            # 调用xinference模型启动接口
            response = requests.post(f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1/models", json=payload)
            # mongodb记录额外参数
            model_uid = params_dict.get("model_uid")
            # params_dict['_id'] = model_uid
            params_dict["status"] = "running"
            params_dict["is_delete"] = False
            params_dict["is_external"] = False
            params_dict["modify_time"] = TimeUtil.get_current_format_time()

            if response.status_code == 200:
                logger.info("->模型启动参数写入mongodb")
                response_by_get = requests.get(f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1/models").json()
                for item in response_by_get.get("data", []):
                    if item.get("id") == params_dict.get("model_uid"):
                        params_dict["max_tokens"] = item.get("context_length")
                        break
                # 写入mongodb
                if (
                    list(
                        MongodbUtil.query_docs_by_condition(
                            collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                            search_condition={"model_uid": model_uid, "is_delete": False, "is_external": False},
                        )
                    )
                    != []
                ):
                    query_filter = {"model_uid": model_uid, "is_external": False}
                    update_operation = {"$set": params_dict}
                    MongodbUtil.update_one(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                        query_filter=query_filter,
                        update_operation=update_operation,
                    )
                else:
                    MongodbUtil.insert_one(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_content=params_dict
                    )
                logger.info("->模型启动参数写入mongodb成功")
                return RetUtil.return_ok(data=f"模型{model_uid}启动成功")
            else:
                # 模型启动异常
                raise Exception(response.json()["detail"])

        except Exception as e:
            detail = f"LLM模型启动异常：{str(e)}"
            return RetUtil.return_error(message=detail)

    @staticmethod
    async def common_model_launch(params_dict: dict):
        """
        启动通用模型
        """
        try:
            if isinstance(params_dict.get("gpu_idx"), list):
                params_dict["gpu_idx"] = list(map(int, params_dict.get("gpu_idx")))
            # 转换为xinference对应参数键值对
            payload = copy.deepcopy(params_dict)
            del payload["mode"]
            del payload["is_realtime"]
            payload["model_name"] = payload.pop("model_id")
            # 是否在GPU上运行
            if payload.get("device") == "GPU":
                logger.info("在GPU上运行")
                payload.pop("device")
                payload["n_gpu"] = "auto"
            else:
                payload.pop("device")
                payload["n_gpu"] = None

            if params_dict.get("model_type") == "embedding":
                model_info = MongodbUtil.query_docs_by_condition(
                    collection_name=CollectionConfig.MODEL_FAMILY_COLLECTION,
                    search_condition={"model_id": params_dict.get("model_id"), "is_remove": 0},
                )
                model_info = list(model_info)
                logger.info(f"嵌入模型家族信息：{model_info}")
                if len(model_info) == 0:
                    detail = "未找到该嵌入模型对应的模型家族,请先创建模型家族"
                    return RetUtil.return_error(message=detail)
                params_dict["max_tokens"] = model_info[0]["model_emb_details"]["model_contex_length"]
                params_dict["embedding_dimension"] = model_info[0]["model_emb_details"]["model_embedding_dimension"]
            if "model_path" in payload and not payload.get("model_path"):
                payload.pop("model_path")

            # 对于bge-m3模型，使用flag引擎
            if payload.get("model_uid") == "bge-m3":
                payload["model_engine"] = "flag"

            # 调用xinference模型启动接口
            response = requests.post(f"{ApiConfig.SUPERVISOR_ENDPOINT}/v1/models", json=payload)
            # mongodb记录额外参数
            model_uid = params_dict.get("model_uid")
            params_dict["status"] = "running"
            params_dict["is_delete"] = False
            params_dict["is_external"] = False
            params_dict["modify_time"] = TimeUtil.get_current_format_time()

            if response.status_code == 200:
                logger.info("->模型启动参数写入mongodb")
                # 写入mongodb
                models = MongodbUtil.query_docs_by_condition(
                    collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                    search_condition={"model_uid": model_uid, "is_delete": False, "is_external": False},
                )
                models = list(models)
                if len(models) != 0:
                    query_filter = {"model_uid": model_uid, "is_external": False}
                    update_operation = {"$set": params_dict}
                    MongodbUtil.update_one(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                        query_filter=query_filter,
                        update_operation=update_operation,
                    )
                else:
                    MongodbUtil.insert_one(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_content=params_dict
                    )
                logger.info("->模型启动参数写入mongodb成功")
                return RetUtil.return_ok(data=f"模型{model_uid}启动成功")
            else:
                # 模型启动异常
                raise Exception(response.json()["detail"])
        except Exception as e:
            logger.exception(f"通用模型启动异常：{str(e)}")
            detail = f"通用模型启动异常：{str(e)}"
            return RetUtil.return_error(message=detail)

    @staticmethod
    async def access_model(params: dict):
        """
        启动通用模型
        """
        try:
            params["is_external"] = True
            params["status"] = "running"
            params["is_delete"] = False
            params["modify_time"] = TimeUtil.get_current_format_time()
            headers = {"Authorization": f"Bearer {params['api_key']}", "Content-Type": "application/json"}

            # 发送 GET 请求以获取支持的模型列表
            response = requests.get(f"{params['api_url']}/models", headers=headers)
            if response.status_code == 200:
                # 解析响应的 JSON 数据
                models = response.json()
                logger.info(f"->支持的模型列表：{models}")
                # 假设返回的数据是一个列表，其中包含模型信息
                model_ids = [model["id"] for model in models["data"]]
                # # 检查模型名称是否在列表中
                if params["model_uid"] in model_ids:
                    results = MongodbUtil.query_docs_by_condition(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                        search_condition={"api_url": params["api_url"], "is_delete": False, "is_external": True},
                    )
                    for result in results:
                        if result["model_uid"] == params["model_uid"]:
                            logger.error(f"此模型{params['model_uid']}已被接入")
                            return RetUtil.return_error(message=f"此模型{params['model_uid']}已被接入")
                    MongodbUtil.insert_one(collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_content=params)
                    return RetUtil.return_ok(f"外部模型{params['model_uid']}接入成功")
                else:
                    logger.error(f"外部模型{params['model_uid']}不在该api_url下")
                    return RetUtil.return_error(message=f"外部模型{params['model_uid']}不在该api_url下")
            else:
                logger.error("请检查api_url和api_key")
                # 打印错误信息
                return RetUtil.return_error(message="请检查api_url和api_key")
        except Exception as e:
            detail = f"外部模型接入异常：{str(e)}"
            logger.error(detail)
            raise

    async def access_model_update(id: str, params: dict):
        """
        启动通用模型
        """
        try:
            headers = {"Authorization": f"Bearer {params['api_key']}", "Content-Type": "application/json"}

            # 发送 GET 请求以获取支持的模型列表
            response = requests.get(f"{params['api_url']}/models", headers=headers)
            if response.status_code == 200:
                # 解析响应的 JSON 数据
                models = response.json()
                # 假设返回的数据是一个列表，其中包含模型信息
                model_ids = [model["id"] for model in models["data"]]
                # # 检查模型名称是否在列表中
                if params["model_uid"] in model_ids:
                    results = MongodbUtil.query_docs_by_condition(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                        search_condition={
                            "api_url": params["api_url"],
                            "_id": {"$ne": ObjectId(id)},
                            "is_delete": False,
                            "is_external": True,
                        },
                    )
                    for result in results:
                        if result["model_uid"] == params["model_uid"]:
                            logger.error(f"此外部模型{params['model_uid']}已被接入")
                            return RetUtil.return_error(message=f"此模型{params['model_uid']}已被接入")
                    MongodbUtil.update_one(
                        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
                        query_filter={"_id": ObjectId(id)},
                        update_operation={"$set": params},
                    )
                    return RetUtil.return_ok("更新成功")
                else:
                    logger.error(f"外部模型{params['model_uid']}不在该api_url下")
                    return RetUtil.return_error(message=f"外部模型{params['model_uid']}不在该api_url下")
            else:
                logger.error("请检查api_url和api_key")
                return RetUtil.return_error(message="请检查api_url和api_key")
        except Exception as e:
            detail = f"更新外部模型异常：{str(e)}"
            logger.error(detail)
            raise
