#!/usr/bin/env python
"""
@Project    :   tiance-base
@File    :   model_family_service.py
@Author  :   WEIHAO HONG
@Time    :   2024/08/28 10:30:51
"""

from loguru import logger
import re

import pymongo
from sqlalchemy.orm import Session

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from service_model_manage.entity.model_famliy_entity import (
    Model_List_Entity,
    Model_Return_Entity,
    ModelFamliyEntity,
    ModelFamliyListEntity,
)
from service_usr_manage.model.usr_model import Usr_Model
# logger = loguru logger (auto-migrated)
class ModelFamilyService:
    _collection_name = CollectionConfig.MODEL_FAMILY_COLLECTION

    @staticmethod
    def get_model_family_by_model_id_and_model_type(model_id, model_type):
        '''
         """
        根据给定的模型 ID 和类型查询模型家族。

        此静态方法尝试从 MongoDB 集合中查询与给定模型 ID 和类型匹配的模型家族。
        查询结果将被转换成 ModelFamliyEntity 对象，并返回其字典表示形式。

        @param[in] model_id str: 要查询的模型 ID。
        @param[in] model_type str: 要查询的模型类型。

        @return: 如果找到符合条件的模型家族，则返回其字典表示形式；
                 如果没有找到或发生错误，则返回空字符串。
        @rtype: dict or str
        '''
        result = ""
        try:
            models = MongodbUtil.query_docs_by_condition(
                ModelFamilyService._collection_name, {"model_id": model_id, "model_type": model_type}
            )
            models = list(models)
            for model in models:
                # print(model)
                if model["is_remove"] == False:
                    result = ModelFamliyEntity(model)
                    return result.to_dict()

        except pymongo.errors.ServerSelectionTimeoutError as e:
            logger.error("MongoDB connection failed: %s", str(e), exc_info=True)
            raise e
        return result

    @staticmethod
    def set_collection_name(collection_name):
        ModelFamilyService._collection_name = collection_name

    @staticmethod
    async def model_create(
        model_id: str,
        model_type: str,
        model_description: str,
        model_llm_details: dict = None,
        model_emb_details: dict = None,
        account_id: str = None,
    ):
        """
        功能说明： 在模型列表数据库中 添加新模型
        :param account_id: 用户id
        :param model_id: 模型名称
        :param model_type: 模型类型
        :param model_description: 模型的相关描述
        :param model_XXX_details: 其他参数，
        """
        # 将模型信息结构化
        model_information = Model_List_Entity(
            model_id, model_type, model_description, model_llm_details, model_emb_details
        ).to_dict()
        # 将用户id添加到结构化的新信息中
        model_information["account_id"] = account_id
        # 存入数据库
        MongodbUtil.insert_one(ModelFamilyService._collection_name, model_information)

        # 返回模型信息 不返回is_remove信息
        return Model_Return_Entity(
            model_id, model_type, model_description, model_llm_details, model_emb_details
        ).to_dict()

    @staticmethod
    async def model_update(
        model_id: str,
        model_type: str,
        model_description: str,
        model_llm_details: dict = None,
        model_emb_details: dict = None,
        account_id: str = None,
    ):
        """
        功能说明： 根据模型id，更新模型相关参数
        :param model_id: 模型名称
        :param model_type: 模型类型
        :param model_description: 模型的相关描述
        :param model_run_details: 其他参数，当 model_type为llm时，才存在非空值。
                                            {"model_engine": ["vllm","transformers"],
                                            "model_format": ["pytorch","gptq"],
                                            "model_size_in_billions": ["7","14"],
                                            "quantazations": ["none","int4","int8"]}
        :param account_id: 用户id
        """

        # 将模型新信息结构化
        model_information = Model_List_Entity(
            model_id, model_type, model_description, model_llm_details, model_emb_details
        ).to_dict()
        # 将用户id添加到结构化的新信息中
        model_information["account_id"] = account_id
        # 新信息取代老信息
        MongodbUtil.replace_docs_by_condition(
            ModelFamilyService._collection_name, search_condition={"_id": model_id}, replace_data=model_information
        )
        # 返回新模型信息 不返回is_remove信息
        return Model_Return_Entity(
            model_id, model_type, model_description, model_llm_details, model_llm_details
        ).to_dict()

    @staticmethod
    async def model_prompt(
        model_id: str,
        model_type: str,
        model_description: str,
        model_llm_details: dict = None,
        model_emb_details: dict = None,
    ):
        return Model_Return_Entity(
            model_id, model_type, model_description, model_llm_details, model_llm_details
        ).to_dict()

    @staticmethod
    async def model_delete(model_id: str, account_id: str = None):
        """
        功能说明： 根据模型id，删除模型（修改标识符 is_remove 为 1 并更新进行该操作的用户id）
        :param model_id: 模型名称，
        :param model_id: 模型名称
        """

        # 修改 is_remove
        MongodbUtil.update_docs_by_condition(
            ModelFamilyService._collection_name,
            search_condition={"model_id": model_id},
            replace_data={"$set": {"is_remove": 1, "account_id": account_id}},
        )

        # 返回修改后模型信息 不返回is_remove信息
        models = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"model_id": model_id})
        model = list(models)
        model = model[0]
        # result = ModelFamliyListEntity(model)
        # return result.to_dict()
        return model

    @staticmethod
    async def get_model_list_by_model_type(model_type: str, model_id: str):
        """
        功能说明： 根据模型类型，返回该类型下的所有模型的基本信息({"model_id:"qwen2-instruct","model_type":"llm","modle_description":"xxx"})
        :param model_type: 模型类型，包括LLM，embedding等
        返回满足条件的模型基本信息列表
        """

        model_list = []
        models = MongodbUtil.query_docs_by_condition(
            ModelFamilyService._collection_name,
            {"model_id": {"$regex": f"{re.escape(model_id)}(\\_.*)?", "$options": "i"}, "model_type": model_type},
        )
        models = list(models)
        for model in models:
            if model["is_remove"] == 0:
                result = ModelFamliyListEntity(model)
                if model_type == "embedding":
                    model_list.append(result.to_dict())
                else:
                    model_list.append(result.to_base_dict())
        new_list = []
        for item in reversed(model_list):
            new_list.append(item)
        return new_list

    @staticmethod
    async def get_model_list_by_model_id(model_id: str):
        model_list = []
        models = MongodbUtil.query_docs_by_condition(ModelFamilyService._collection_name, {"model_id": model_id})
        models = list(models)
        for model in models:
            if model["is_remove"] == 0:
                result = ModelFamliyListEntity(model)
                model_list.append(result.to_prompt_dict())
        new_list = []
        for item in reversed(model_list):
            new_list.append(item)
        return new_list[0]

    @staticmethod
    async def model_prompt_info(
        model_id: str,
        model_type: str,
        model_description: str,
        model_llm_details: dict = None,
        model_emb_details: dict = None,
    ):
        """
        功能说明： 根据模型id，更新模型相关参数
        :param model_id: 模型名称
        :param model_type: 模型类型
        :param model_description: 模型的相关描述
        :param model_run_details: 其他参数，当 model_type为llm时，才存在非空值。
                                            {"model_engine": ["vllm","transformers"],
                                            "model_format": ["pytorch","gptq"],
                                            "model_size_in_billions": ["7","14"],
                                            "quantazations": ["none","int4","int8"]}
        """

        # 返回新模型信息 不返回is_remove信息
        return Model_Return_Entity(
            model_id, model_type, model_description, model_llm_details, model_llm_details
        ).to_dict()

    @staticmethod
    async def get_user_attribute_by_account_id(db: Session, account_id: str):
        """
        功能说明： 根据用户id, 查询attribute值, 返回用户权限
        0 普通用户
        1 管理员
        """
        user_info = db.query(Usr_Model).filter(Usr_Model.account_id == account_id).first()
        if user_info is None:
            return None
        user_attribute = user_info.attribute
        return user_attribute

    @staticmethod
    async def get_account_id_by_user_attribute(db: Session, user_attribute: str, account_id: str):
        """
        功能说明： 根据用户id, 查询attribute值, 返回用户权限
        0 普通用户 获取所有管理员权限的id
        1 管理员 获取所有用户id
        """
        # 管理员，获取所有用户id创建的工具
        if user_attribute:
            admin_info = db.query(Usr_Model).filter(Usr_Model.attribute == 1, Usr_Model.status == 1).all()
            user_info = []

        # 普通用户，获取所有管理员id以及自己id创建的工具
        else:
            admin_info = db.query(Usr_Model).filter(Usr_Model.attribute == 1, Usr_Model.status == 1).all()
            user_info = db.query(Usr_Model).filter(Usr_Model.account_id == account_id).all()

        user_id_list = [i.account_id for i in user_info]
        admin_id_list = [i.account_id for i in admin_info]

        return user_id_list, admin_id_list


if __name__ == "__main__":
    # 初始化数据库连接
    MongodbUtil.connect()

    # 获取模型启动信息
    # model = ModelFamilyService.get_model_family_by_model_id_and_model_type('llama', 'LLM')

    # 新增模型
    # model_run_details = {
    #     'model_engine': ['vllm', 'transformers'],
    #     'model_format': ['pytorch', 'gptq'],
    #     'model_size_in_billions': ['6', '12'],
    #     'quantazations': ['none', 'int4', 'int8']
    # }
    # model = ModelFamilyService.model_create(model_id='baichuan', model_type='LLM', model_description='good LLM', model_run_details=model_run_details)

    # 更新修改模型
    # model_run_details = {
    #     'model_engine': ['vllm', 'transformers'],
    #     'model_format': ['pytorch', 'gptq'],
    #     'model_size_in_billions': ['6', '12'],
    #     'quantazations': ['none', 'int4', 'int8']
    # }
    # model =  ModelFamilyService.model_update(model_id='new_GPs', model_type='LLM', model_description='a good good LLM',
    #                                         model_run_details=model_run_details)

    # 删除模型（is_remove = 1）
    # model = ModelFamilyService.model_delete(model_id='baichuan')

    # 显示指定类型的模型信息
    models = ModelFamilyService.get_model_list_by_model_type(model_type="LLM")
    # for model in models:
    #     print(model)

    # model = ModelFamilyService.get_model_family_by_model_id_and_model_type('llama', 'LLM')
    # print(model)

    MongodbUtil.close()
