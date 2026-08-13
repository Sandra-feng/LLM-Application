
from base_utils.ret_util import RetUtil
from base_utils.mongodb_util import MongodbUtil
from base_utils.log_util import LogUtil

class ConfigService(object):
    """
    配置服务
    """

    @staticmethod
    async def get_model_type_list():
        """
        获取模型类型列表
        :return:
        """
        # 获取数据索引
        data_index = MongodbUtil.query_docs_by_condition(collection_name="model_config",
                                                         search_condition={"model_type": {"$exists": True}})
        # 按照格式组织数据
        data_list = []
        output_list = []
        for data in data_index:
            data_list = data.get('model_type')
            labels = ["语言模型", "嵌入模型", "重排模型", "语音模型", "图像模型"]
            output_list = [
                {"label": label, "name": name}
                for label, name in zip(labels, data_list)
            ]
        return output_list

    @staticmethod
    async def get_model_engine_list():
        """
        获取模型引擎列表
        :return:
        """
        data_index = MongodbUtil.query_docs_by_condition(collection_name="model_config",
                                                         search_condition={"model_engine": {"$exists": True}})
        # 按照格式组织数据
        data_list = []
        for data in data_index:
            data_list = data.get("model_engine")
            data_list = {"model_engine_list": data_list}
        return data_list

    @staticmethod
    async def get_model_quantization_list():
        """
        获取模型量化类型列表
        :return:
        """
        data_index = MongodbUtil.query_docs_by_condition(collection_name="model_config",
                                                         search_condition={"quantization": {"$exists": True}})
        # 按照格式组织数据
        data_list = []
        for data in data_index:
            data_list = data.get("quantization")
            data_list = {"model_quantization_list": data_list}
        return data_list

    @staticmethod
    async def get_model_size_list():
        """
        获取模型大小列表
        :return:
        """
        data_index = MongodbUtil.query_docs_by_condition(collection_name="model_config",
                                                         search_condition={"model_size": {"$exists": True}})
        # 按照格式组织数据
        data_list = []
        for data in data_index:
            data_list = data.get("model_size")
            data_list = {"model_size_list": data_list}
        return data_list

    @staticmethod
    async def get_model_format_list():
        """
        获取模型形式列表
        :return:
        """
        data_index = MongodbUtil.query_docs_by_condition(collection_name="model_config",
                                                         search_condition={"model_format": {"$exists": True}})
        # 按照格式组织数据
        data_list = []
        for data in data_index:
            data_list = data.get('model_format')
            data_list = {"model_format_list": data_list}
        return data_list

