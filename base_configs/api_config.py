#!/usr/bin/env python
# -*- coding: UTF-8 -*-
"""
@Project ：tiance-base
@File    ：api_config.py
@Author  ：TaoMeng
@Date    ：2024/8/25 22:49
"""


class ApiConfig:
    """
    API配置
    """

    SERVICE_IP = "0.0.0.0"

    # 服务端口
    SERVICE_PORT = 9101

    # 服务端口

    # Xinference主节点endpoint
    SUPERVISOR_ENDPOINT = "http://10.8.21.164:9997"

    # 小模型部署地址
    Small_Model_Address = "http://10.8.21.165:8100"

    # 小模型外部接口
    Outside_Model_Address = "http://10.8.21.164:9100"

    # MCP外部接口地址
    MCP_OUTSIDE_URL = "http://10.8.21.164:9103"

    # MCP工具链接
    MCP_TOOL_URL = "http://10.8.21.164:9103/mcp_server/"

    # MCP智能体链接
    MCP_AGENT_URL = "http://10.8.21.164:9103/mcp/server/"

    # 稀疏模型权重地址
    Sparse_Model = "bge-m3"
    # 文件切块批次大小
    Batch_Size = 50

    # 创建向量数据库索引类型
    index_type = "GPU_IVF_FLAT"

    # 根路由
    ROOT_ROUTE = "/tc/llm/base"

    # 配置管理路由
    CONFIG_MANAGE_ROUTE = "/config/manage"

    # 模型管理路由
    MODEL_MANAGE_ROUTE = "/model/manage"

    # 知识库管理路由
    KNOWLEDGE_MANAGE_ROUTE = "/knowledge/manage"

    # 工具管理路由
    TOOLSET_MANAGE_ROUTE = "/toolset/manage"

    # 数据集管理路由
    DATASET_MANAGE_ROUTE = "/dataset/manage"

    # 智能体管理路由
    AGENT_MANAGE_ROUTE = "/agent/manage"

    # 工作流管理路由
    WORKFLOW_MANAGE_ROUTE = "/workflow/manage"

    # 提示词管理路由
    PROMPT_MANAGE_ROUTE = "/prompt/manage"
    # 提示词管理路由
    Synonym_ROUTE = "/synonym/manage"

    # 权限管理路由
    PERMISSION_MANAGE_ROLE_ROUTE = "/permission-manage/role"
    PERMISSION_MANAGE_AUTH_ROUTE = "/permission-manage/auth"
    PERMISSION_MANAGE_CONFIG_ROUTE = "/permission-manage/config"
    PERMISSION_MANAGE_RESOURCE_ROUTE = "/permission-manage/resource"
    PERMISSION_MANAGE_TEAM_ROUTE = "/permission-manage/team"

    # 鉴权路由
    PERMISSION_AUTH_ROUTE = "/permission-auth"

    # 用户管理路由
    USR_MANAGE_ROUTE = "/user-manage"

    # API 版本
    MODEL_SERVICE_VERSION = "v0.1"
    #  forbiddin_word_prompt = """你是一个内容安全检查助手，专门负责判断用户输入是否违禁、不合法合规或涉及敏感内容。
    #                      ## 检查标准
    #                      请根据以下标准判断用户输入是否违禁：
    #                      ### 1. 违法内容
    #                      - 违反中国法律法规的内容
    #                      - 煽动分裂国家、破坏国家统一的内容
    #                      - 泄露国家机密、危害国家安全的内容
    #                      - 宣扬恐怖主义、极端主义的内容
    #                      - 破坏民族团结、煽动民族仇恨的内容
    #                      ### 2. 色情内容
    #                      - 直接或间接描述性行为的内容
    #                      - 涉及未成年人色情的内容
    #                      - 淫秽语言、色情暗示或挑逗性内容
    #                      - 宣扬卖淫、嫖娼等非法性交易的内容
    #                      ### 3. 暴力内容
    #                      - 详细描述暴力行为、血腥场面
    #                      - 宣扬暴力、鼓励伤害他人或自残
    #                      - 恐怖、残忍的虐待场景描述
    #                      - 教唆犯罪方法或暴力手段
    #                      ### 4. 敏感话题
    #                      - 攻击中国政府、中国共产党及其领导人的内容
    #                      - 歪曲历史、否定革命先烈的内容
    #                      - 涉及邪教、封建迷信的内容
    #                      - 可能引发社会不稳定的谣言或虚假信息
    #                      ### 5. 其他违禁内容
    #                      - 侵犯他人隐私、诽谤侮辱他人的内容
    #                      - 涉及赌博、毒品等违法活动的内容
    #                      - 商业广告、营销推广内容
    #                      - 侵犯知识产权的内容

    #                      ## 判断规则

    #                      1. 如果用户输入明显违反上述任何一条标准，请直接标记为"违禁"
    #                      2. 如果内容处于灰色地带或边界情况，也判断为"违禁"
    #                      3. 只有完全符合法律法规和社会主义核心价值观的内容才能标记为"安全"
    #                      4. 用户问图中有什么不安全行为的时候输出安全即可
    #                      ## 输出格式
    #                      你的输出只能是安全或者违禁"""

    forbiddin_word_prompt = """你是一名内容安全判定助手，仅可输出两个字。
任务：判断用户提问是否包含任何“人名”。
规则：
人名包括中外真实或可能指向真人的称呼，如“张三”、“Trump”、“老李”、“小明”、“Lisa”。
不含人名 → 输出 安全
含人名 → 输出 违禁
无论任何情况只返回“安全”或“违禁”，禁止解释、禁止多余字符。"""

    detect_prompt = """
    你是极智安全环保大模型。具备丰富的现场巡检、安全管理与隐患识别经验。  
    
你的任务是分析图片内容，判断是否存在**明显的不安全行为**，并以正式、分层的 Markdown 格式输出检测结果。

---

### 📋 输出逻辑要求
1. **若图片中存在明显的不安全行为：**  
   请输出以下三部分：  
   - 🖼️ 场景描述  
   - ⚠️ 不安全行为识别  
   - 🛠️ 整改建议  
   **禁止输出“✅ 安全结论”部分。**

2. **若图片中未发现任何明显的不安全行为：**  
   仅输出：  
   - 🖼️ 场景描述  
   - ✅ 安全结论  

3. 语气要求：  
   - 正式、客观、专业；  
   - 使用行业标准表达（如“存在明显不安全行为”“建议立即整改”）；  
   - 禁用“我认为”“可能”“似乎”等主观词。

---

### 🔍 重点识别的不安全行为类别
请重点检测以下安全隐患类别（可多项）：


人员风险：包括未规范穿戴劳保用品（如安全带、手套）、睡觉、吸烟、依靠栏杆、未扶扶手等；
设备状态：设备断电、设备出入口堵塞、气体瓶倾倒、格栅板缺失或破损等；
物料泄露：液体飞溅、动火作业火花飞溅、蒸汽泄露等；
环境风险：起火、地面积水、厂房漏雨、地面结冰等；
管理风险：无关人员进入、乱扯电线、未配备消防器材、未封闭车间大门等。


---

### 🧱 输出格式示例

#### ✅ 示例 1：发现明显不安全行为
---

### 🖼️ 场景描述
图片显示一名作业人员正在橙色梯子上进行操作，身体前倾，双手扶梯，脚踩踏板。

### ⚠️ 不安全行为识别
- **人员在爬梯口作业**：作业人员未采取防坠落措施（未佩戴安全带或防坠落装置）；  
- **未规范佩戴安全帽**：安全帽帽带未系紧，存在脱落风险；  
- **未穿戴整齐劳保**：未佩戴手套和防护眼镜，存在划伤及眼部受伤风险。

### 🛠️ 整改建议
1. 立即停止作业，正确佩戴安全帽并系紧帽带；  
2. 佩戴防护眼镜、手套和安全带，确保安全带固定在可靠锚点上；  
3. 作业前检查梯子稳固，保持作业环境整洁；  
4. 加强作业人员安全培训，提升规范操作意识。  

---

#### ✅ 示例 2：未发现不安全行为
---

### 🖼️ 场景描述
图片显示车间环境整洁，作业人员穿戴规范，设备运行正常。

### ✅ 安全结论
未发现明显不安全行为，整体安全状态良好。

"""

    # MCP管理路由
    MCP_MANAGE_ROUTE = "/mcp/manage"
