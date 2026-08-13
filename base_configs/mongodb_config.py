

class MongodbConfig(object):
    """
    mongodb配置信息
    """

    # mongodb配置
    MONGODB_HOST = "10.8.21.164"
    MONGODB_PORT = 27017
    MONGODB_USER = "tansun"
    MONGODB_PASS = "Tansun@2024.com"
    MONGODB_DB = "tiance_base"
    AUTH_MECHANISM = "SCRAM-SHA-256"


class CollectionConfig(object):
    """
    collection配置信息
    """
    # 模型启动信息集合名
    MODEL_RUN_COLLECTION = "model_run_info"

    # 模型信息集合名
    MODEL_FAMILY_COLLECTION = "model_list_test"

    # 知识库基础信息
    KB_COLLECTION = "kb_list_info"

    # 工具基础信息
    TOOL_COLLECTION = "tool_list_info"

    # 工具配置信息
    TOOL_INFO_COLLECTION = "tool_config_info"

    # 嵌入模型信息
    EMBEDDING_COLLECTION = "embedding_model_list"

    # 智能体基础信息
    AGENT_COLLECTION = "agent_list_info"

    # 编排智能体基础信息
    ARRANGE_AGENT_COLLECTION = "arrange_agent_list_info"

    # 工作流基础信息
    WORKFLOW_COLLECTION = "workflow_list_info"

    # 工作流编排信息
    WORKFLOW_ARRANGE_COLLECTION = "workflow_arrange_info"

    # 工作流节点执行信息
    WORKFLOW_NODE_EXECUTE_COLLECTION = "workflow_node_execute_info"

    # 角色信息
    ROLE_COLLECTION = "role_list_info"

    # 资源信息
    RES_COLLECTION = "res_list_info"

    # 资源信息
    ROLE_RES_COLLECTION = "role_res_relation"

    # 资源信息
    ROLE_MEM_COLLECTION = "role_mem_relation"

    # 账号信息
    USR_COLLECTION = "usr_info"

    # 配置文件信息
    CONFIG_FILE_COLLECTION = "config_file_info"

    # 配置数据集信息
    CONFIG_DATASET_COLLECTION = "config_dataset_info"

    # 配置训练任务信息
    CONFIG_TRAIN_COLLECTION = "train_task_info"

    # 配置训练参数信息
    CONFIG_TRAIN_PARAMS_COLLECTION = "train_params_info"

    # 配置上传文件信息
    UPLOAD_FILE_INFO_COLLECTION = "upload_file_info"

    # 类别字典表
    SYS_STATIC_DICT_TYPE = "sys_static_dict_type"

    # 子类别字典表
    SYS_STATIC_DICT_ITEMS = "sys_static_dict_items"

    # 文件解析结果表
    FILE_PARSE_RESULT = "file_parse_result"

    # 文件解析结果表
    KB_ARRANGE_INFO = "kb_arrange_info"

    # 同义词组绑定表
    SYNONYM_BINDING = "synonym_binding"

    # 切片数据表
    CHUNK_COLLECTION = "parent_chunk"

    # 外部mcp配置表
    OUTSIDE_MCP_CONFIG = "outside_mcp_config"

    # 内部mcp配置表
    INSIDE_MCP_CONFIG = "inside_mcp_config"


    # 切片高亮引用节点缓存
    # 用途：在检索完成后，将 (kb_id, chunk_id) 对应的 reference_node 存入该集合，供高亮接口直接读取
    CHUNK_REFERENCE_NODE_COLLECTION = "chunk_reference_node"
