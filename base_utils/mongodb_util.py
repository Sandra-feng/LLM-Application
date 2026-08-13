
from pymongo import MongoClient

from base_configs.mongodb_config import CollectionConfig, MongodbConfig

# 重构新增，这里后续需要导入全部
from data_access.implementations.mongo_repository import MongoRepository


# 创建一个mongodb的单例实例。
# 用于导入静态MongodbUtil类的应用程序的所有部分
# 现在将得到这个实例，它符合相同的接口。
# 后续若需要使用其他NoSQL数据库，只需要继承MongoRepositoryabc基类，并实现其中的方法即可。
# todolist:
# 1. 根据.env文件，实例化对应的数据库
# 2. 将实例化后的数据库对象，赋值给MongodbUtil
# 3. 在MongodbUtil类中，使用实例化后的数据库对象，进行数据库操作
class _MongoUtilFacade:
    """
    一个外观类，充当实际 MongoRepository 实例的全局代理。
    它允许业务逻辑代码继续使用 MongodbUtil.method() 的方式调用，
    而实例的生命周期则在 main.py 中集中管理。
    """

    _client: "MongoRepository" = None

    def initialize(self, client: "MongoRepository"):
        """在应用启动时由 main.py 调用，注入真实的客户端实例。"""
        self._client = client

    def __getattr__(self, name):
        """
        当访问 MongodbUtil 的任何属性时（如 insert_one），
        此方法会将调用转发给内部持有的真实 _client 实例。
        """
        if self._client is None:
            raise RuntimeError(
                "MongodbUtil has not been initialized. Ensure it is initialized in the FastAPI lifespan."
            )
        return getattr(self._client, name)


MongodbUtil = _MongoUtilFacade()


# class MongodbUtil(object):
#     """
#     mongodb工具类：pymongo和mongodb版本应该对应，避免出现一些奇怪的问题
#     """
#     __db = None
#     __client = None
#
#     @staticmethod
#     def connect():
#         """
#         连接mongodb
#         :return:
#         """
#         MongodbUtil._get_connection()
#
#     @staticmethod
#     def reconnect():
#         """
#         重新连接mongodb
#         :return:
#         """
#         MongodbUtil.close()
#         MongodbUtil.connect()
#
#     @staticmethod
#     def close():
#         """
#         重新连接mongodb
#         :return:
#         """
#         MongodbUtil.__client.close()
#         MongodbUtil.__db = None
#
#     @staticmethod
#     def _get_connection():
#         """
#         获取mongodb连接信息
#         :return:
#         """
#         if MongodbUtil.__db is None:
#             # 开启连接保活功能（防止长时间不使用连接导致断开）
#             MongodbUtil.__client = MongoClient(host=MongodbConfig.MONGODB_HOST, port=MongodbConfig.MONGODB_PORT,
#                                                username=MongodbConfig.MONGODB_USER, password=MongodbConfig.MONGODB_PASS,
#                                                authSource=MongodbConfig.MONGODB_DB, authMechanism=MongodbConfig.AUTH_MECHANISM)
#             MongodbUtil.__db = MongodbUtil.__client[MongodbConfig.MONGODB_DB]
#
#     @staticmethod
#     def coll(collection_name):
#         """
#         获取指定集合的数据索引
#         :param collection_name:集合名称
#         :return:
#         """
#         return MongodbUtil.__db[collection_name]
#
#     @staticmethod
#     def insert_one(collection_name, doc_content):
#         """
#         插入单条数据
#         :param collection_name: 集合名称
#         :param doc_content: 文档内容
#         :return:
#         """
#         return MongodbUtil.coll(collection_name).insert_one(doc_content)
#
#     @staticmethod
#     def insert_many(collection_name, doc_content_list):
#         """
#         插入多条数据
#         :param collection_name: 集合名称
#         :param doc_content_list: 文档内容列表
#         :return:
#         """
#         MongodbUtil.coll(collection_name).insert_many(doc_content_list)

#     @staticmethod
#     def update_one(collection_name, query_filter, update_operation):
#         """
#         更新单条数据
#         :param collection_name: 集合名称
#         :param query_filter: 筛选条件
#         :param update_operation: 更新内容
#         :return:
#         """
#         MongodbUtil.coll(collection_name).update_one(query_filter, update_operation)

#     @staticmethod
#     def update_many(collection_name, query_filter, update_operation):
#         """
#         更新多条数据
#         :param collection_name: 集合名称
#         :param query_filter: 筛选条件
#         :param update_operation: 更新内容
#         :return:
#         """
#         MongodbUtil.coll(collection_name).update_many(query_filter, update_operation)

#     @staticmethod
#     def del_doc_by_id(collection_name, doc_id):
#         """
#         根据文档id删除文档
#         :param collection_name: 集合名称
#         :param doc_id: 文档id
#         :return:
#         """
#         res = MongodbUtil.coll(collection_name).delete_one({'_id': doc_id})
#         return res.deleted_count

#     @staticmethod
#     def del_docs_by_condition(collection_name, del_condition=None):
#         """
#         功能说明： 使用字典的格式，进行条件删除
#         :param collection_name: 数据表名称
#         :param del_condition: 删除条件，只能是dict类型，key大于等于一个即可，也可为空
#                         可使用修饰符删除：{"name": {"$gt": "H"}}  #读取 name 字段中第一个字母 ASCII 值大于 "H" 的数据
#                         使用正则表达式删除：{"$regex": "^R"}    #读取 name 字段中第一个字母为 "R" 的数据
#         :return:
#         """
#         res = MongodbUtil.coll(collection_name).delete_many(del_condition)
#         return res.deleted_count

#     @staticmethod
#     def get_collection_names():
#         """
#         获取数据库的所有集合名称
#         :return:
#         """
#         return MongodbUtil.__db.collection_names()

#     @staticmethod
#     def query_all_doc(collection_name):
#         """
#         查询某个集合的所有文档
#         :param collection_name: 集合名称
#         :return:
#         """
#         return MongodbUtil.coll(collection_name).find({})

#     @staticmethod
#     def query_doc_by_id(collection_name, doc_id):
#         """
#         基于mongodb查询数据
#         :param collection_name: 集合名称
#         :param doc_id: 文档id
#         :return:
#         """
#         return MongodbUtil.coll(collection_name).find_one({'_id': doc_id})

#     @staticmethod
#     def query_docs_by_condition(collection_name, search_condition=None):
#         """
#         功能说明： 使用字典的格式，进行条件查询获取数据
#         :param collection_name: 数据表名称
#         :param search_condition: 只能是dict类型，key大于等于一个即可，也可为空
#                         可使用修饰符查询：{"name": {"$gt": "H"}}  #读取 name 字段中第一个字母 ASCII 值大于 "H" 的数据
#                         使用正则表达式查询：{"$regex": "^R"}    #读取 name 字段中第一个字母为 "R" 的数据
#         :return:
#         """
#         # 只会返回数据的索引，数据需要自己取
#         result = MongodbUtil.coll(collection_name).find(search_condition)
#         return result

#     @staticmethod
#     def update_docs_by_condition(collection_name, search_condition=None, replace_data=None):
#         """
#         功能说明： 根据search_condition，更新符合条件文档中的某些数据
#         :param collection_name: 数据表名称
#         :param search_condition: 只能是dict类型，key大于等于一个即可，也可为空
#                         可使用修饰符查询：{"name": {"$gt": "H"}}  #读取 name 字段中第一个字母 ASCII 值大于 "H" 的数据
#                         使用正则表达式查询：{"$regex": "^R"}    #读取 name 字段中第一个字母为 "R" 的数据
#         :param replace_data：用来更新的数据 例{"$set": {"is_remove":1}}
#         :return:
#         """
#         return MongodbUtil.coll(collection_name).update_one(search_condition, replace_data)

#     @staticmethod
#     def replace_docs_by_condition(collection_name, search_condition=None, replace_data=None):
#         """
#         功能说明： 根据search_condition，直接用replace_data取代符合条件的数据
#         :param collection_name: 数据表名称
#         :param search_condition: 只能是dict类型，key大于等于一个即可，也可为空
#                         可使用修饰符查询：{"name": {"$gt": "H"}}  #读取 name 字段中第一个字母 ASCII 值大于 "H" 的数据
#                         使用正则表达式查询：{"$regex": "^R"}    #读取 name 字段中第一个字母为 "R" 的数据
#         :param replace_data：用来更新的数据
#         :return:
#         """
#         return MongodbUtil.coll(collection_name).replace_one(search_condition, replace_data)

#     def query_data(doc_id, results):
#         start_time = time.time()
#         result = MongodbUtil.query_doc_by_id(CollectionConfig.WORKFLOW_ARRANGE_COLLECTION, doc_id)
#         end_time = time.time()
#         results.append(end_time - start_time)
#         print(f"查询ID为{doc_id}的文档，耗时：{end_time - start_time}秒")
#         print(result)

#     def find_one_and_update(collection_name, search_condition=None, replace_data=None):
#         return MongodbUtil.coll(collection_name).find_one_and_update(search_condition, replace_data, upsert=True)

#     @staticmethod
#     def query_docs_by_condition_pagination(collection_name, search_condition=None, page=1, page_size=0, sort_field="_id", reverse=True):
#         """
#         分页查询
#         :param collection_name: 数据库名
#         :param search_condition: 查询条件
#         :param page: 页序号（以1起始）
#         :param page_size: 一页的大小
#         :param sort_field: 排序项
#         :param reverse: 是否倒序
#         """
#         result = (MongodbUtil.coll(collection_name).find(search_condition)
#                   .sort(sort_field, DESCENDING if reverse else ASCENDING)
#                   .sort("_id", DESCENDING)
#                   .skip((page - 1) * page_size)
#                   .limit(page_size))
#         return result

#     @staticmethod
#     def count_documents_by_condition(collection_name, search_condition=None):
#         """查询符合条件的条目数量"""
#         return MongodbUtil.coll(collection_name).count_documents(search_condition)

if __name__ == "__main__":
    from pymongo import MongoClient

    # 连接到 MongoDB
    client = MongoClient(
        host=MongodbConfig.MONGODB_HOST,
        port=MongodbConfig.MONGODB_PORT,
        username=MongodbConfig.MONGODB_USER,
        password=MongodbConfig.MONGODB_PASS,
        authSource=MongodbConfig.MONGODB_DB,
        authMechanism=MongodbConfig.AUTH_MECHANISM,
    )

    # 选择数据库
    db = client[MongodbConfig.MONGODB_DB]  # 确保数据库名称正确

    # 选择集合
    collection_name = CollectionConfig.MODEL_RUN_COLLECTION  # 确保 CollectionConfig 已正确定义
    documents = db[collection_name]  # 获取集合对象
    # documents.update_many({}, [{'$set': {'is_external': False}}])
    # print("更新成功")
    # original_collection = db['model_run_info1']
    # new_collection = db['model_run_info']

    # # 遍历原始集合中的所有文档
    # for doc in original_collection.find():
    #     # 删除原始文档的 _id 字段
    #     doc.pop('_id', None)
    #     # 将修改后的文档插入到新集合中
    #     new_collection.insert_one(doc)
    # 1.上面是修改模型运行表 _id

    # 更新所有文档
    # documents.update_many({}, [{'$set': {'is_external': Fal上面为模型运行添加内部模型字段se}}])
    # print("更新成功")
    # 2.

    # MongodbUtil.connect()
    # result = MongodbUtil.query_docs_by_condition(collection_name="model_run_info",search_condition={})
    # print(list(result))
    # embedd_data = []
    # rerank_data = []
    # results = MongodbUtil.query_docs_by_condition(collection_name=CollectionConfig.MODEL_RUN_COLLECTION,search_condition={"is_external": False, "model_type": "embedding", "is_delete":False})
    # for result in results:
    #     embedd_data.append({"id": str(result["_id"]),"model_uid": result["model_uid"], "model_name": result["model_uid"]})
    # results = MongodbUtil.query_docs_by_condition(collection_name=CollectionConfig.MODEL_RUN_COLLECTION,search_condition={"is_external": False, "model_type": "rerank", "is_delete":False})
    # for result in results:
    #     rerank_data.append({"id": str(result["_id"]),"model_uid": result["model_uid"], "model_name": result["model_uid"]})
    # print(embedd_data)
    # print(rerank_data)
    #
    # results = MongodbUtil.query_docs_by_condition(collection_name=CollectionConfig.KB_COLLECTION,
    #                                               search_condition={})
    # for result in results:
    #     for data in embedd_data:
    #         if result["embedding_model"] == data["model_uid"]:
    #             embedding_id = data["id"]
    #             print(f"embedding_id:{embedding_id}")
    #     for data in rerank_data:
    #         if result["rerank_model"] == data["model_uid"]:
    #             rerank_id = data["id"]
    #             print(f"rerank_id:{rerank_id}")
    #             print("\n")
    #
    #     MongodbUtil.update_one(collection_name=CollectionConfig.KB_COLLECTION,query_filter={"_id":result["_id"]},update_operation={"$set": {"embedding_id": embedding_id, "rerank_id": rerank_id}})
    # 3.为知识库表添加新的字段

    # MongodbUtil.connect()
    # LLM_data = []
    # rerank_data = []
    # results = MongodbUtil.query_docs_by_condition(collection_name=CollectionConfig.MODEL_RUN_COLLECTION,search_condition={"is_external": False, "model_type": "LLM", "is_delete":False})
    # for result in results:
    #     LLM_data.append({"id": str(result["_id"]),"model_uid": result["model_uid"], "model_name": result["model_uid"]})
    # results = MongodbUtil.query_docs_by_condition(collection_name=CollectionConfig.MODEL_RUN_COLLECTION,search_condition={"is_external": False, "model_type": "rerank", "is_delete":False})
    # for result in results:
    #     rerank_data.append({"id": str(result["_id"]),"model_uid": result["model_uid"], "model_name": result["model_uid"]})
    # print(LLM_data)
    # print(rerank_data)
    # results = MongodbUtil.query_docs_by_condition(collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION,search_condition={})
    # for result in results:
    #     for data in LLM_data:
    #         if result["model_params"]["model_uid"] == data["model_uid"]:
    #             result["model_params"]["id"] = data["id"]
    #             result["model_params"]["model_name"] = data["model_name"]
    #             result["model_params"]["presence_penalty"] = 0
    #             result["model_params"]["frequency_penalty"] = 0
    #             print(f"model_params:{result['model_params']}")
    #     for data in rerank_data:
    #         if result["recall_setting"]["rerank_model"] == data["model_uid"]:
    #             result["recall_setting"]["rerank_name"] = data["model_name"]
    #             result["recall_setting"]["rerank_id"] = data["id"]
    #             print(f"recall_setting{result['recall_setting']}")
    #             print("\n")
    #
    #     MongodbUtil.update_one(collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION,query_filter={"_id":result["_id"]},update_operation={"$set": {"model_params": result['model_params'], "recall_setting": result['recall_setting']}})
    # 4.智能体更新

    MongodbUtil.initialize(client.get_database(MongodbConfig.MONGODB_DB))
    LLM_data = []
    rerank_data = []
    results = MongodbUtil.query_docs_by_condition(
        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
        search_condition={"is_external": False, "model_type": "LLM", "is_delete": False},
    )
    for result in results:
        LLM_data.append({"id": str(result["_id"]), "model_uid": result["model_uid"], "model_name": result["model_uid"]})
    results = MongodbUtil.query_docs_by_condition(
        collection_name=CollectionConfig.MODEL_RUN_COLLECTION,
        search_condition={"is_external": False, "model_type": "rerank", "is_delete": False},
    )
    for result in results:
        rerank_data.append(
            {"id": str(result["_id"]), "model_uid": result["model_uid"], "model_name": result["model_uid"]}
        )
    print(LLM_data)
    print(rerank_data)
    results = MongodbUtil.query_docs_by_condition(
        collection_name=CollectionConfig.WORKFLOW_ARRANGE_COLLECTION, search_condition={}
    )
    for result in results:
        nodes = result["workflow_graph"]["nodes"]
        # print(f"nodes:{nodes}")
        for index, node in enumerate(nodes):
            if node["type"] == "llm":
                llm_node = node["data"]["llmNodeList"]
                for data in LLM_data:
                    if llm_node["model_uid"] == data["model_uid"]:
                        MongodbUtil.update_one(
                            CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,
                            query_filter={"_id": result["_id"]},
                            update_operation={
                                "$set": {
                                    f"workflow_graph.nodes.{index}.data.llmNodeList.model_name": data["model_name"],
                                    f"workflow_graph.nodes.{index}.data.llmNodeList.id": data["id"],
                                }
                            },
                        )
            elif node["type"] == "knowledge":
                knowledge_node = node["data"]["retrieval_setting"]["recall_setting"]
                for data in rerank_data:
                    if knowledge_node["rerank_model"] == data["model_uid"]:
                        print(f"_id:{result['_id']}")
                        MongodbUtil.update_one(
                            CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,
                            query_filter={"_id": result["_id"]},
                            update_operation={
                                "$set": {
                                    f"workflow_graph.nodes.{index}.data.retrieval_setting.recall_setting.rerank_name": data[
                                        "model_name"
                                    ],
                                    f"workflow_graph.nodes.{index}.data.retrieval_setting.recall_setting.rerank_id": data[
                                        "id"
                                    ],
                                }
                            },
                        )
                print(llm_node)
                print("\n")

        # for data in LLM_data:
        #     if result["model_params"]["model_uid"] == data["model_uid"]:
        #         result["model_params"]["id"] = data["id"]
        #         result["model_params"]["model_name"] = data["model_name"]
        #         result["model_params"]["presence_penalty"] = 0
        #         result["model_params"]["frequency_penalty"] = 0
        #         print(f"model_params:{result['model_params']}")
        # for data in rerank_data:
        #     if result["recall_setting"]["rerank_model"] == data["model_uid"]:
        #         result["recall_setting"]["rerank_name"] = data["model_name"]
        #         result["recall_setting"]["rerank_id"] = data["id"]
        #         print(f"recall_setting{result['recall_setting']}")
        #         print("\n")
        #
        # MongodbUtil.update_one(collection_name=CollectionConfig.ARRANGE_AGENT_COLLECTION,query_filter={"_id":result["_id"]},update_operation={"$set": {"model_params": result['model_params'], "recall_setting": result['recall_setting']}})
    # 4.工作流更新

    # # # 新增
    # # MongodbUtil.insert_many("tiance_test", [
    # #     {"_id": "ef6b95601a850548c29a20562d060991", "type": "one", "content": "content"},
    # #     {"_id": "1280094035955941376", "type": "one", "content": "content"},
    # #     {"_id": "b528c4806102ef9401f616063e33db42", "type": "two", "content": "content"},
    # #     {"_id": "82082716189f80fd070b89ac716570ba", "type": "two", "content": "content"}
    # # ])
    #
    # # 查询
    # # doc_list = MongodbUtil.query_docs_by_condition('tiance_test', search_condition={"type": "two"})
    # # for item in doc_list:
    # #     print(item['_id'], item)
    #
    # # 删除文档
    # # count = MongodbUtil.del_doc_by_id("tiance_test", "1280094035955941376")
    # # print(count)
    # import time
    # start_time = time.time()
    # # MongodbUtil.insert_one(collection_name=CollectionConfig.CONFIG_TRAIN_PARAMS_COLLECTION, doc_content=["Qwen1.5-0.5B-Chat-GPTQ-Int4","Qwen2.5-7B-Instruct","Qwen2-7B-Instruct","Qwen2-7B-Instruct-GPTQ-Int4","Qwen2-72B-Instruct","Qwen2-72B-Instruct-GPTQ-Int4","Qwen2.5-7B="])
    # result = MongodbUtil.query_doc_by_id(collection_name=CollectionConfig.WORKFLOW_ARRANGE_COLLECTION,doc_id=ObjectId('67c12e09ed6305d731ca2c93'))
    # print(f"查询时间为:{time.time()-start_time}")
    # # print(result["workflow_graph"])
    # import time
    # import threading
    # def query_data(doc_id, results):
    #     MongodbUtil.connect()
    #     start_time = time.time()
    #     result = MongodbUtil.query_doc_by_id(CollectionConfig.WORKFLOW_ARRANGE_COLLECTION, doc_id)
    #     end_time = time.time()
    #     results.append(end_time - start_time)
    #     print(f"查询ID为{doc_id}的文档，耗时：{end_time - start_time}秒")
    #
    #
    # doc_id = ObjectId('67c12e09ed6305d731ca2c93')  # 替换为您要查询的文档ID
    # thread_count = 1  # 并发线程数
    #
    # threads = []
    # results = []
    #
    # for _ in range(thread_count):
    #     thread = threading.Thread(target=query_data, args=(doc_id, results))
    #     threads.append(thread)
    #     thread.start()
    #
    # for thread in threads:
    #     thread.join()
    #
    # if results:  # 确保results不为空
    #     average_time = sum(results) / len(results)
    #     print(f"并发查询的平均响应时间为：{average_time:.2f}秒")
    # else:
    #     print("没有成功的查询记录，无法计算平均响应时间。")
