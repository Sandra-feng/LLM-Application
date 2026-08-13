"""
@Project    :   tiance-base
@File    :   model_supervise_service.py
@Author  :   WEIHAO HONG
@Time    :   2024/08/27 14:22:56
"""

import asyncio
from loguru import logger
import re

import pymongo
import requests
from fabric import Connection

from base_configs.mongodb_config import CollectionConfig
from base_configs.xinference_config import XinferenceConfig
from base_utils.mongodb_util import MongodbUtil
from base_utils.time_util import TimeUtil
from service_model_manage.entity.common_type import ModelType
from service_model_manage.entity.launch_entity import CommonModelInfo, LLMModelInfo
from service_model_manage.service.launch_service import LaunchService
# logger = loguru logger (auto-migrated)
class ModelSuperviseService:
    _header = {}
    _collection_name = CollectionConfig.MODEL_RUN_COLLECTION

    @staticmethod
    def _update_data_helper(model_uid: str, field_name: str, field_value):
        """
        @brief 更新指定模型的指定字段值。

        此函数通过模型的唯一标识符查找模型，并更新指定字段的值。如果更新成功，则记录日志并返回True；如果失败，则返回False。

        @param model_uid 模型的唯一标识符。
        @param field_name 需要更新的字段名。
        @param field_value 需要设置的新字段值。
        @return 如果更新成功，返回True；否则返回False。

        @exception pymongo.errors.ServerSelectionTimeoutError 如果连接到MongoDB服务器超时，则抛出此异常。
        """
        try:
            logger.debug(
                "准备更新模型字段: model_uid=%s, field_name=%s, field_value=%s", model_uid, field_name, field_value
            )
            t = TimeUtil.get_current_format_time()
            result = MongodbUtil.update_docs_by_condition(
                ModelSuperviseService._collection_name,
                {"model_uid": model_uid, "is_delete": False, "is_external": False},
                {"$set": {field_name: field_value, "modify_time": t}},
            )
            if result.matched_count > 0:
                logger.info("模型更新成功: model_uid=%s, 更新字段=%s", model_uid, field_name)
                return True, t
            else:
                logger.warning("模型更新失败: 未匹配到符合条件的记录 model_uid=%s, 更新字段=%s", model_uid, field_name)
        except pymongo.errors.ServerSelectionTimeoutError as e:
            logger.error("MongoDB 连接超时: model_uid=%s, field_name=%s", model_uid, field_name, exc_info=True)
            raise e

    @staticmethod
    def _get_error_string(response: requests.Response) -> str:
        """
        @brief 从HTTP响应中提取错误信息。

        此函数尝试从HTTP响应的JSON内容中提取错误信息。如果提取失败，则尝试获取HTTP错误状态。如果两者都失败，返回一个通用的错误信息。

        @param response HTTP响应对象，类型为`requests.Response`。
        @return 返回包含错误详情的字符串。如果无法提取具体错误信息，返回"Unknown error"。
        """
        try:
            if response.content:
                return response.json()["detail"]
        except Exception:
            pass
        try:
            response.raise_for_status()
        except requests.HTTPError as e:
            return str(e)
        return "Unknown error"

    @staticmethod
    async def run_commands_via_xinference_cmdline(command):
        commands = []
        command_prompt = "xinference"
        if XinferenceConfig.XINFERENCE_CMD:
            logger.debug("Using abs path call %s", XinferenceConfig.XINFERENCE_CMD)
            command_prompt = XinferenceConfig.XINFERENCE_CMD + " "

        commands.append(command)
        # 建立连接
        with Connection(
            host=XinferenceConfig.SERVICE_IP,
            user=XinferenceConfig.SERVER_USER,
            connect_kwargs={"password": XinferenceConfig.SERVER_PASSWORD},
        ) as conn:
            # 使用伪终端执行命令
            for command in commands:
                command = command_prompt + command
                result = conn.run(command, pty=True)

        return result.stdout, result.stderr

    @staticmethod
    async def xinference_get_models_wraper():
        # try
        result = requests.get(
            "http://{0}:{1}/v1/models".format(XinferenceConfig.SERVICE_IP, XinferenceConfig.SERVICE_PORT)
        )
        # except ConnectionError as e:
        #     raise e
        return result.json()

    @staticmethod
    async def get_models(model_type: str, page: int, page_size: int, model_id: str):
        """
        @brief 根据模型类型异步获取模型列表。

        此静态异步方法调用 xinference 服务，以获取特定类型的模型列表。
        它解析返回的数据，并根据模型的类型和状态构建一个模型字典列表。

        @param[in] model_type str: 要查询的模型类型。
        @param[in] page str: 页码。
        @param[in] page_size str: 分页大小。
        @return: 一个包含模型信息的字典列表。
        @model_id: 模型id
        @rtype: List[dict]
        """
        # stdout,stderr = await ModelSuperviseService.run_commands_via_xinference_cmdline("list")
        t_models = []
        try:
            t_models = MongodbUtil.query_docs_by_condition_pagination(
                ModelSuperviseService._collection_name,
                {
                    "model_uid": {"$regex": f".*{re.escape(model_id)}.*", "$options": "i"},
                    "model_type": model_type,
                    "is_delete": False,
                    "is_external": False,
                },
                page=page,
                page_size=page_size,
                sort_field="_id",
                reverse=False,
            )
            len_result = MongodbUtil.count_documents_by_condition(
                ModelSuperviseService._collection_name,
                {
                    "model_uid": {"$regex": f".*{re.escape(model_id)}.*", "$options": "i"},
                    "model_type": model_type,
                    "is_delete": False,
                    "is_external": False,
                },
            )
        except pymongo.errors.ServerSelectionTimeoutError as e:
            logger.error("server_connect_timeout: %s", e, exc_info=True)
            raise e
        t_models = list(t_models)
        models = await ModelSuperviseService.xinference_get_models_wraper()
        models = models["data"]
        # print(models)
        """
        {
            object': 'list', 
            'data': [
                {
                    'id': 'bge-base-zh-v1.5', 
                    'object': 'model',
                    'created': 0,
                    'owned_by': 'xinference', 
                    'model_type': 'embedding', 
                    'address': '0.0.0.0: 37009', 
                    'accelerators': ['0'],
                    'model_name': 'bge-base-zh-v1.5', 
                    'dimensions': 768, 
                    'max_tokens': 512, 
                    'language': ['zh'],
                    'model_revision': 'v0.0.1',
                    'replica': 1
                },
                {
                    'id': 'qwen2-instruct', 
                    'object': 'model', 
                    'created': 0, 
                    'owned_by': 'xinference', 
                    'model_type': 'LLM', 
                    'address': '0.0.0.0:44095', 
                    'accelerators': ['1', '2'], 
                    'model_name': 'qwen2-instruct', 
                    'model_lang': ['en', 'zh'], 
                    'model_ability': ['chat', 'tools'], 
                    'model_description': 'Qwen2 is the new series of Qwen large language models', 
                    'model_format': 'pytorch', 
                    'model_size_in_billions': '0_5', 
                    'model_family': 'qwen2-instruct', 
                    'quantization': 'none', 
                    'model_hub': 'huggingface', 
                    'revision': None, 
                    'context_length': 32768, 
                    'replica': 1}
            ]
        }
        """
        t_model_map = {}
        for model in models:
            if model["model_type"] == model_type:
                t_model_map[model["id"]] = model
        result_model = []
        for d_model in t_models:
            t = None
            if d_model["model_uid"] in t_model_map:
                model = t_model_map[d_model["model_uid"]]
                if model["model_type"] == ModelType.LLM.value:
                    t = None
                    if d_model["status"] != "running":
                        result, t = ModelSuperviseService._update_data_helper(d_model["model_uid"], "status", "running")
                    t_model = {}
                    t_model["id"] = str(d_model["_id"])
                    t_model["model_name"] = model["model_name"]
                    t_model["model_uid"] = model["id"]
                    t_model["address"] = model["address"]
                    t_model["gpu_idx"] = model["accelerators"]
                    t_model["model_size_in_billions"] = model["model_size_in_billions"]
                    t_model["quantization"] = model["quantization"]
                    t_model["replica"] = model["replica"]
                    t_model["status"] = "running"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    if d_model.get("max_tokens", None) is not None:
                        t_model["max_tokens"] = d_model["max_tokens"]
                    result_model.append(t_model)

                else:
                    if d_model["status"] != "running":
                        result, t = ModelSuperviseService._update_data_helper(d_model["model_uid"], "status", "running")
                    t_model = {}
                    t_model["id"] = str(d_model["_id"])
                    t_model["model_name"] = model["model_name"]
                    t_model["model_uid"] = model["id"]
                    t_model["address"] = model["address"]
                    t_model["gpu_idx"] = model["accelerators"]
                    t_model["model_size_in_billions"] = ""
                    t_model["quantization"] = ""
                    t_model["replica"] = model["replica"]
                    t_model["status"] = "running"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    if model["model_type"] == ModelType.AUDIO.value:
                        t_model["mode"] = d_model["mode"]
                    if d_model.get("max_tokens", None) is not None:
                        t_model["max_tokens"] = d_model["max_tokens"]
                    result_model.append(t_model)

            else:
                if d_model["status"] != "stop":
                    result, t = ModelSuperviseService._update_data_helper(d_model["model_uid"], "status", "stop")
                if d_model["model_type"] == ModelType.LLM.value:
                    t_model = {}
                    t_model["id"] = str(d_model["_id"])
                    t_model["model_name"] = d_model["model_id"]
                    t_model["model_uid"] = d_model["model_uid"]
                    t_model["address"] = ""
                    t_model["gpu_idx"] = ""
                    t_model["model_size_in_billions"] = d_model["model_size_in_billions"]
                    t_model["quantization"] = d_model["quantization"]
                    t_model["replica"] = d_model["replica"]
                    t_model["status"] = "stop"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    if d_model.get("max_tokens", None) is not None:
                        t_model["max_tokens"] = d_model["max_tokens"]
                    result_model.append(t_model)

                else:
                    t_model = {}
                    t_model["id"] = str(d_model["_id"])
                    t_model["model_name"] = d_model["model_id"]
                    t_model["model_uid"] = d_model["model_uid"]
                    t_model["address"] = ""
                    t_model["gpu_idx"] = ""
                    t_model["model_size_in_billions"] = ""
                    t_model["quantization"] = ""
                    t_model["replica"] = d_model["replica"]
                    t_model["status"] = "stop"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    if d_model["model_type"] == ModelType.AUDIO.value:
                        t_model["mode"] = d_model["mode"]
                    if d_model.get("max_tokens", None) is not None:
                        t_model["max_tokens"] = d_model["max_tokens"]
                    result_model.append(t_model)

        """
        {
            “status": "true", 
            "msg": "success", 
            "data": [
                {
                    "model_name":"qwen2-instruct",
                    "model_uid":"qwen2-7B-instruct",
                    "address":"10.8.21.164",
                    "gpu_idx":"1,2",
                    "model_size_in_billions":"7",
                    "quantization":"Int4",
                    "replica":1
                }
            ]
        }
        """
        return {"total": len_result, "result": result_model}

    @staticmethod
    async def get_runing_rerank_models(model_type: str):
        """
        @brief 根据模型类型异步获取模型列表。

        此静态异步方法调用 xinference 服务，以获取特定类型的模型列表。无需分页返回
        它解析返回的数据，并根据模型的类型和状态构建一个模型字典列表。

        @param[in] model_type str: 要查询的模型类型。
        @return: 一个包含模型信息的字典列表。
        @rtype: List[dict]
        """
        # stdout,stderr = await ModelSuperviseService.run_commands_via_xinference_cmdline("list")
        t_models = []
        try:
            t_models = MongodbUtil.query_docs_by_condition(
                ModelSuperviseService._collection_name,
                {"model_type": model_type, "is_delete": False, "is_external": False},
            )
        except pymongo.errors.ServerSelectionTimeoutError as e:
            logger.error("server_connect_timeout")
            raise e
        t_models = list(t_models)
        models = await ModelSuperviseService.xinference_get_models_wraper()

        models = models["data"]
        # print(models)
        """
        {
            object': 'list', 
            'data': [
                {
                    'id': 'bge-base-zh-v1.5', 
                    'object': 'model',
                    'created': 0,
                    'owned_by': 'xinference', 
                    'model_type': 'embedding', 
                    'address': '0.0.0.0: 37009', 
                    'accelerators': ['0'],
                    'model_name': 'bge-base-zh-v1.5', 
                    'dimensions': 768, 
                    'max_tokens': 512, 
                    'language': ['zh'],
                    'model_revision': 'v0.0.1',
                    'replica': 1
                },
                {
                    'id': 'qwen2-instruct', 
                    'object': 'model', 
                    'created': 0, 
                    'owned_by': 'xinference', 
                    'model_type': 'LLM', 
                    'address': '0.0.0.0:44095', 
                    'accelerators': ['1', '2'], 
                    'model_name': 'qwen2-instruct', 
                    'model_lang': ['en', 'zh'], 
                    'model_ability': ['chat', 'tools'], 
                    'model_description': 'Qwen2 is the new series of Qwen large language models', 
                    'model_format': 'pytorch', 
                    'model_size_in_billions': '0_5', 
                    'model_family': 'qwen2-instruct', 
                    'quantization': 'none', 
                    'model_hub': 'huggingface', 
                    'revision': None, 
                    'context_length': 32768, 
                    'replica': 1}
            ]
        }
        """
        t_model_map = {}
        for model in models:
            if model["model_type"] == model_type:
                t_model_map[model["id"]] = model
        result_model = []
        for d_model in t_models:
            t = None
            if d_model["model_uid"] in t_model_map:
                model = t_model_map[d_model["model_uid"]]
                if model["model_type"] == ModelType.LLM.value:
                    t = None
                    if d_model["status"] != "running":
                        result, t = ModelSuperviseService._update_data_helper(d_model["model_uid"], "status", "running")
                    t_model = {}
                    t_model["model_name"] = model["model_name"]
                    t_model["model_uid"] = model["id"]
                    t_model["address"] = model["address"]
                    t_model["gpu_idx"] = model["accelerators"]
                    t_model["model_size_in_billions"] = model["model_size_in_billions"]
                    t_model["quantization"] = model["quantization"]
                    t_model["replica"] = model["replica"]
                    t_model["status"] = "running"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    result_model.append(t_model)

                    #   其他模型没有大小和量化选项
                else:
                    if d_model["status"] != "running":
                        result, t = ModelSuperviseService._update_data_helper(d_model["model_uid"], "status", "running")
                    t_model = {}
                    t_model["model_name"] = model["model_name"]
                    t_model["model_uid"] = model["id"]
                    t_model["address"] = model["address"]
                    t_model["gpu_idx"] = model["accelerators"]
                    t_model["model_size_in_billions"] = ""
                    t_model["quantization"] = ""
                    t_model["replica"] = model["replica"]
                    t_model["status"] = "running"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    result_model.append(t_model)

            else:
                if d_model["status"] != "stop":
                    result, t = ModelSuperviseService._update_data_helper(d_model["model_uid"], "status", "stop")
                if d_model["model_type"] == ModelType.LLM.value:
                    t_model = {}
                    t_model["model_name"] = d_model["model_id"]
                    t_model["model_uid"] = d_model["model_uid"]
                    t_model["address"] = ""
                    t_model["gpu_idx"] = ""
                    t_model["model_size_in_billions"] = d_model["model_size_in_billions"]
                    t_model["quantization"] = d_model["quantization"]
                    t_model["replica"] = d_model["replica"]
                    t_model["status"] = "stop"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    result_model.append(t_model)

                    #   其他模型没有大小和量化选项
                else:
                    t_model = {}
                    t_model["model_name"] = d_model["model_id"]
                    t_model["model_uid"] = d_model["model_uid"]
                    t_model["address"] = ""
                    t_model["gpu_idx"] = ""
                    t_model["model_size_in_billions"] = ""
                    t_model["quantization"] = ""
                    t_model["replica"] = d_model["replica"]
                    t_model["status"] = "stop"
                    t_model["modify_time"] = t if t else d_model["modify_time"]
                    result_model.append(t_model)

        """
        {
            “status": "true", 
            "msg": "success", 
            "data": [
                {
                    "model_name":"qwen2-instruct",
                    "model_uid":"qwen2-7B-instruct",
                    "address":"10.8.21.164",
                    "gpu_idx":"1,2",
                    "model_size_in_billions":"7",
                    "quantization":"Int4",
                    "replica":1
                }
            ]
        }
        """
        # result = result_model
        result = {"result": result_model}
        return result

    @staticmethod
    async def xinference_terminate_model_wraper(model_uid: str):
        """
        异步终止服务器上运行的特定模型。

        该方法通过发送 DELETE 请求到 Xinference 服务，以终止指定的模型。
        如果请求成功，将返回 True。如果请求失败，将抛出 RuntimeError。

        @param[in] model_uid str: 要终止的模型的唯一标识符。
        @return bool: 如果模型成功终止，则返回 True。
        @raise RuntimeError: 如果无法终止模型，将抛出此异常，并提供失败的详细信息。

        @note 该方法使用 HTTP DELETE 请求来终止模型。
        """
        url = f"http://{XinferenceConfig.SERVICE_IP}:{XinferenceConfig.SERVICE_PORT}/v1/models/{model_uid}"
        logger.debug("sending signal to %s", url)
        response = requests.delete(url, headers=ModelSuperviseService._header)
        logger.debug("response %s", response)
        if response.status_code != 200:
            raise RuntimeError(
                f"Failed to terminate model, detail: {ModelSuperviseService._get_error_string(response)}"
            )

        return True

    @staticmethod
    async def pause_model(model_uid: str):
        """
        异步暂停服务器上的特定模型。

        该方法调用 xinference_terminate_model_wraper 来暂停指定的模型。
        这通常用于临时停止模型的运行，以便进行维护或其他操作。

        @param model_uid str: 要暂停的模型的唯一标识符。
        @return bool: 如果模型成功暂停，则返回 True。
        @raise RuntimeError: 如果模型无法暂停，将抛出此异常。

        @note 该方法实际上是对 xinference_terminate_model_wraper 的一个封装，用于暂停模型。
        """
        is_success = False
        try:
            models = MongodbUtil.query_docs_by_condition(
                ModelSuperviseService._collection_name,
                {"model_uid": model_uid, "is_delete": False, "is_external": False},
            )
            models = list(models)
            if len(models) > 1:
                logger.warning("model_uid %s has multiple records", model_uid)
            elif len(models) == 0:
                raise RuntimeError("Failed to terminate model, detail: model not exits")
            is_success = await ModelSuperviseService.xinference_terminate_model_wraper(model_uid=model_uid)
            result, t = ModelSuperviseService._update_data_helper(model_uid, "status", "stop")

        except pymongo.errors.ServerSelectionTimeoutError as e:
            logger.error("server_connect_timeout", exc_info=True)
            raise e

        return is_success

    @staticmethod
    async def restart_model(model_uid: str):
        """
        @brief 重启指定的模型。

        此函数首先尝试暂停指定的模型，如果暂停成功，则输出日志信息，表示模型已停止或不存在。

        @param model_uid 模型的唯一标识符。
        @return 返回True表示函数执行成功。
        """
        logger.debug("restart model %s", model_uid)
        is_stop = False
        start_model_info = {}
        try:
            models = MongodbUtil.query_docs_by_condition(
                ModelSuperviseService._collection_name,
                {"model_uid": model_uid, "is_delete": False, "is_external": False},
            )
            models = list(models)
            if len(models) > 1:
                logger.warning("model_uid %s has multiple records", model_uid)
            elif len(models) == 0:
                raise RuntimeError("Failed to terminate model, detail: model not exits")
            start_model_info = models[0]
        except pymongo.errors.ServerSelectionTimeoutError as e:
            logger.error("server_connect_timeout", exc_info=True)
            raise e

        try:
            is_stop = await ModelSuperviseService.pause_model(model_uid)
        except RuntimeError as e:
            # print("enter")
            logger.info("模型停止失败: %s", e.args[0])
        if is_stop:
            logger.debug("model_stop %s", model_uid)
        else:
            logger.debug("model already stop or not exists %s", model_uid)

        # print("start_model_info  {}".format(start_model_info))
        logger.info("start model %s", model_uid)
        if start_model_info["model_type"] == ModelType.LLM.value:
            params_dict = dict(LLMModelInfo(**start_model_info))
            response = await LaunchService.llm_model_launch(params_dict)
            if not response.get("status"):
                logger.error("LLM模型启动失败")
                raise RuntimeError("llm_model_launch  error{}".format(response.get("message")))
        else:
            params_dict = dict(CommonModelInfo(**start_model_info))
            response = await LaunchService.common_model_launch(params_dict)
            if not response.get("status"):
                logger.error("通用模型启动失败")
                raise RuntimeError("common_model_launch  error{}".format(response.get("message")))

        return True

    @staticmethod
    async def delete_model(model_uid: str):
        """
        @brief 删除指定的模型。

        此函数首先尝试暂停指定的模型，然后将模型的删除状态更新为True。

        @param model_uid 模型的唯一标识符。
        @return 返回True表示函数执行成功。
        """
        logger.debug("delete model %s", model_uid)
        is_stop = False
        try:
            is_stop = await ModelSuperviseService.pause_model(model_uid)
        except RuntimeError as e:
            # print("enter")
            logger.info("model_stop failed: %s", e.args[0])
        if is_stop:
            logger.debug("model_stop %s", model_uid)
        else:
            logger.debug("model already stop or not exists %s", model_uid)
        ModelSuperviseService._update_data_helper(model_uid, "is_delete", True)
        return True


if __name__ == "__main__":
    MongodbUtil.connect()
    # 初始化日志
    # LogUtil.init(process_name="tiance-base-config")
    # asyncio.run(ModelSuperviseService().get_models("LLM"))
    asyncio.run(ModelSuperviseService().delete_model("qwen2-instruct"))
