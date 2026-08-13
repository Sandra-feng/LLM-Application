
from base_utils.ret_util import RetUtil
from base_utils.mongodb_util import MongodbUtil


class ConfigService(object):
    """
    配置服务
    """

    @staticmethod
    def get_model_type_list():
        """
        获取模型类型列表
        :return:
        """
        # 获取数据索引
        data_index = MongodbUtil.query_docs_by_condition(collection_name="tiance-config",
                                                         search_condition={"config_type": "model_type"})
        # 按照格式组织数据
        data_list = []
        for data in data_index:
            data_list.append(data[""])
        return RetUtil.return_ok(data=data_list)
