class MySQLConfig:
    """
    mongodb配置信息
    """

    # mongodb配置
    MySQL_HOST = "10.8.21.165"
    MySQL_PORT = 3306
    MySQL_USER = "root"
    MySQL_PASS = "Admin%402024"  # 真实密码 Admin@2024
    MySQL_DB = "tiance_base_dev"


class TableConfig:
    """
    表信息
    """

    # 账号信息
    USR_TABLE = "user_info"
    USR_RELATION_TABLE = "user_relation_info"
    ROLE_TABLE = "role_info"
    RES_TABLE = "res_info"
    ROLE_RES_TABLE = "role_res_relation"
    ROLE_MEM_TABLE = "role_mem_relation"
    ACC_TOKEN_TABLE = "account_token"
    CONFIG_TABLE = "config_info_new"
    CHAT_INFO_TABLE = "chat_info"
    CHAT_STOP_INFO_TABLE = "chat_stop_info"
    MEM_CHAT_TABLE = "mem_chat"
    TEAM_INFO_TABLE = "team_info"
    TEAM_MEM_TABLE = "team_mem_relation"
    PROMPT_TABLE = "prompt_info"
    QUESTION_TABLE = "talk_question"
    KNOWLEDGE_EVALUATION = "knowledge_evaluation"
    KNOWLEDGE_EVALUATION_SETTING = "evaluation_setting"
    EVALUATION_QUESTION= "evaluation_question"
    EVALUATION_ANSWER = "evaluation_answer"
    EVALUATION_RESULT = "evaluation_result"

