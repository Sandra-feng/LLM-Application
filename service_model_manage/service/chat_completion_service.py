import base64
import re
from io import BytesIO
from urllib.parse import urljoin

import openai
import requests
from bson import ObjectId
from loguru import logger
from openai.types.chat import ChatCompletion
from PIL import Image
from sqlalchemy.orm import Session

from base_configs.api_config import ApiConfig
from base_configs.minio_config import MinioConfig
from base_configs.model_config import ModelConfig
from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from service_model_manage.entity.chat_completion_entity import (
    ChatCompletionRequestParams,
    ChatCompletionRequestParams_v1,
    Multimodel_ChatParams,
    multi_model_ChatCompletionRequestParams,
    vl_ChatCompletionRequestParams,
)
from service_model_manage.service.chat_db_service import ChatConversationService
from service_permission_manage.service.config_service import ConfigService


# logger = loguru logger (auto-migrated)
class OpenAILLMService:
    def __init__(self, id):
        # logger.info("初始化 OpenAILLMService | 模型ID={}", id)
        result = MongodbUtil.query_doc_by_id(collection_name=CollectionConfig.MODEL_RUN_COLLECTION, doc_id=ObjectId(id))
        if result["is_external"] == True:
            # logger.info("api_key长度: %d", len(result["api_key"]))
            self.llm_model_client = openai.Client(api_key=result["api_key"], base_url=result["api_url"], timeout=30)
            self.async_llm_model_client = openai.AsyncClient(
                api_key=result["api_key"], base_url=result["api_url"], timeout=30
            )
            # logger.info("外部模型已完成初始化")
        else:
            self.llm_model_client = openai.Client(api_key=ModelConfig.LLM_API_KEY, base_url=ModelConfig.LLM_API_BASE)
            self.async_llm_model_client = openai.AsyncClient(
                api_key=ModelConfig.LLM_API_KEY, base_url=ModelConfig.LLM_API_BASE, timeout=30
            )
            # logger.info("已使用内部模型完成初始化")

    def stream_chat(self, request: ChatCompletionRequestParams) -> ChatCompletion:
        messages = self.parse_messages(request=request)
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            stream=True,
        )
        return completion_stream

    def encode_to_base64(self, image_input):
        """
        将图片对象、图片路径或Base64编码的图片数据转换为Base64编码的图片数据。
        :param image_input: 图片对象、图片路径或Base64编码的图片数据。
        :return: Base64编码的图片数据。
        """
        response = requests.get(image_input)

        # 检查请求是否成功
        if response.status_code == 200:
            # 使用 BytesIO 打开图片
            image_input = Image.open(BytesIO(response.content))
        # image_input = Image.open(image_input) # 图生文模型的图片路径得先转成Image对象才能转换成base64编码输入给模型的
        # 检查是否已经是Base64编码的字符串
        if isinstance(image_input, str) and (
            image_input.startswith("data:image")
            or (len(image_input) % 4 == 0 and not image_input.strip().lower().startswith("http"))
        ):
            return image_input

        # 检查是否是PIL图片对象
        elif isinstance(image_input, Image.Image):
            # 将PIL图片对象转换为Base64
            buffered = BytesIO()
            image_input.save(buffered, format="PNG")
            base64_data = base64.b64encode(buffered.getvalue()).decode("utf-8")
            while len(base64_data) % 4 != 0:
                base64_data += "="
            return base64_data
        # 检查是否是文件路径
        elif isinstance(image_input, str):
            try:
                # 尝试将文件路径转换为Base64
                with open(image_input, "rb") as image_file:
                    base64_data = base64.b64encode(image_file.read()).decode("utf-8")
                    while len(base64_data) % 4 != 0:
                        base64_data += "="
                    return base64_data
            except OSError:
                # 如果路径无效，返回错误信息
                return "Invalid image path."

        # 如果输入类型不支持，返回错误信息
        else:
            return "Unsupported input type."

    def vl_stream_chat(
        self, request: vl_ChatCompletionRequestParams, db: Session, chunk_content, type
    ) -> ChatCompletion:
        messages = self.parse_messages_vl(db=db, request=request, chunk_content=chunk_content, type=type)
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            stream=True,
        )
        return completion_stream

    def parse_messages_vl(
        self, request: multi_model_ChatCompletionRequestParams, chunk_content, type, db: Session
    ) -> list:
        # 解析历史聊天
        messages = []
        if request.system_prompts:
            messages.append(
                {"role": "system", "content": request.system_prompts + f"请结合以下内容回答问题：《{chunk_content}》"}
            )
        else:
            system_prompts = f"请结合以下内容回答问题：《{chunk_content}》"
            messages.append({"role": "system", "content": system_prompts})
        talk_info = ChatConversationService.check_talk_info_history(
            db=db, conversation_id=request.conversation_id, type=type
        )
        # LogUtil.info(f"talk_info:--{talk_info}")
        if len(talk_info) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-(request.history + 1) : -1]
        else:
            chatbot = talk_info
        for idx, conversation in enumerate(chatbot):  # 循环遍历聊天记录
            # 存在模型消息，添加到消息列表中
            if conversation["user"] and conversation["assistant"]["content"] != "":
                if "images" in conversation:
                    if len(conversation["images"]) > 0:
                        change_conversation = []
                        for i, image in enumerate(conversation["images"]):
                            change_conversation.append(urljoin(f"http://{MinioConfig.END_POINT}", image))
                        image_b64_img = []
                        for image in change_conversation:
                            # LogUtil.info(str(type(image)))
                            image_b64_img.append(self.encode_to_base64(image))
                        image_contents = [
                            {"type": "image_url", "image_url": {"url": f"data:image;base64,{b64_img}"}}
                            for b64_img in image_b64_img
                        ]
                        messages.append(
                            {
                                "role": "user",
                                "content": image_contents + [{"type": "text", "text": conversation["user"]}],
                            }
                        )
                else:
                    messages.append({"role": "user", "content": conversation["user"]})
            else:
                pass
            if (
                conversation["assistant"]
                and conversation["assistant"] != "'[]'"
                and conversation["assistant"]["content"] != ""
            ):
                # LogUtil.info(f"conversation['assistant']:--{conversation['assistant']}")
                messages.append({"role": "assistant", "content": conversation["assistant"]["content"]})
            else:
                pass
        # LogUtil.log_json(
        #     describe="->实际输入LLM对话记录",
        #     kwargs=jsonable_encoder({"real_chat_messages": messages}),
        # )
        if request.images:
            image_b64_img = []
            request_images = []
            for i, image in enumerate(request.images):
                request_images.append(urljoin(f"http://{MinioConfig.END_POINT}", image))
            for image in request_images:
                # LogUtil.info(str(type(image)))
                image_b64_img.append(self.encode_to_base64(image))
            image_contents = [
                {"type": "image_url", "image_url": {"url": f"data:image;base64,{b64_img}"}} for b64_img in image_b64_img
            ]
            messages.append(
                {
                    "role": "user",
                    "content": image_contents + [{"type": "text", "text": request.retrival_params.user_query}],
                }
            )
        else:
            messages.append({"role": "user", "content": request.retrival_params.user_query})
        return messages

    def vl_chunk_chat(
        self, request: vl_ChatCompletionRequestParams, db: Session, chunk_content, type
    ) -> ChatCompletion:
        image_b64_img = []
        for image in request.image:
            image_b64_img.append(self.encode_to_base64(image))
        image_contents = [
            {"type": "image_url", "image_url": {"url": f"data:image;base64,{b64_img}"}} for b64_img in image_b64_img
        ]
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=[
                {
                    "role": "system",
                    "content": [{"type": "text", "text": request.system_prompts}],
                },
                {"role": "user", "content": image_contents + [{"type": "text", "text": request.question}]},
            ],
            # temperature=request.temperature,
            # max_tokens=request.max_token_length,
            stream=False,
        )
        return completion_stream

    def chunk_chat(
        self, request: multi_model_ChatCompletionRequestParams, db: Session, chunk_content, type
    ) -> ChatCompletion:
        messages = self.parse_messages_file(
            db=db, request=request, chunk_content=chunk_content, type=type, model_list=[]
        )
        completion = self.llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            stream=False,
        )
        return completion.choices[0].message.content

    def chunk_chat_transform(self, request: multi_model_ChatCompletionRequestParams) -> ChatCompletion:
        messages = self.parse_messages(request=request)
        completion = self.llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            stream=False,
        )
        return completion.choices[0].message.content

    def parse_messages(self, request: ChatCompletionRequestParams) -> list:
        messages = []
        if request.system_prompts:
            messages.append({"role": "system", "content": request.system_prompts})
        if request.chatbot is not None and len(request.chatbot) == 0:  # 没有历史聊天记录
            messages.append({"role": "user", "content": request.question})
            # 记录日志
            # LogUtil.log_json(
            #     describe="->实际输入LLM对话记录",
            #     kwargs=jsonable_encoder({"real_chat_messages": messages}),
            # )
            return messages
        else:  # 解析历史聊天
            if len(request.chatbot) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
                if request.history == 0:
                    chatbot = []
                else:
                    chatbot = request.chatbot[-request.history :]
            else:
                chatbot = request.chatbot
            for idx, conversation in enumerate(chatbot):  # 循环遍历聊天记录
                # 如果当前是最后一条记录，并且没有模型消息，则将用户消息添加到列表中并结束循环
                if idx == len(request.chatbot) - 1 and not conversation["assistant"]:
                    messages.append({"role": "user", "content": conversation["assistant"]})
                    break
                # 存在用户消息，添加到消息列表中
                if conversation["user"]:
                    messages.append({"role": "user", "content": conversation["user"]})
                # 存在模型消息，添加到消息列表中
                if conversation["assistant"]:
                    messages.append({"role": "assistant", "content": conversation["assistant"]})
            messages.append(
                {"role": "user", "content": request.retrival_params.user_query}
            )  # 循环结束后，添加用户当前的查询
            return messages

    def chunk_chat_v1(self, request: ChatCompletionRequestParams_v1) -> ChatCompletion:
        messages = self.parse_messages_v1(request=request)
        completion = self.llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            stream=False,
        )
        return completion.choices[0].message.content

    def stream_chat_v1(
        self, request: ChatCompletionRequestParams_v1, db: Session, chunk_content, type
    ) -> ChatCompletion:
        messages = self.parse_messages_v1(
            db=db, request=request, chunk_content=chunk_content, type=type, model_list=[], rewrite_query=""
        )
        # logger.info(
        #     "stream_chat_v1历史messages: 类型=%s, 长度=%d",
        #     type(messages).__name__,
        #     len(messages) if hasattr(messages, "__len__") else "N/A",
        # )
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            stream=True,
        )
        return completion_stream

    def stream_chat_v1_with_penalty(
        self, request: ChatCompletionRequestParams_v1, db: Session, chunk_content, type
    ) -> ChatCompletion:
        messages = self.parse_messages_v1(
            db=db, request=request, chunk_content=chunk_content, type=type, model_list=[], rewrite_query=""
        )
        # logger.info(
        #     "stream_chat_v1_with_penalty历史messages: 类型=%s, 长度=%d",
        #     type(messages).__name__,
        #     len(messages) if hasattr(messages, "__len__") else "N/A",
        # )
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            stream=True,
        )
        return completion_stream

    def stream_chat_v1_with_Synonyms(
        self, request: ChatCompletionRequestParams_v1, db: Session, chunk_content, type, model_list, rewrite_query
    ) -> ChatCompletion:
        messages = self.parse_messages_v1(
            db=db,
            request=request,
            chunk_content=chunk_content,
            type=type,
            model_list=model_list,
            rewrite_query=rewrite_query,
        )
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            stream=True,
        )
        return completion_stream

    async def workflow_stream_chat_v1_with_penalty(
        self, request: ChatCompletionRequestParams_v1, db: Session, chunk_content, type, model_list
    ):
        messages = self.parse_messages_v1(
            db=db, request=request, chunk_content=chunk_content, type=type, model_list=model_list, rewrite_query=""
        )

        # 创建原始流
        completion_stream = await self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            stream=True,
        )

        # 改为异步生成器：遍历并yield每个chunk
        async for chunk in completion_stream:
            yield chunk

    def parse_messages_v1(
        self, request: ChatCompletionRequestParams_v1, chunk_content, type, model_list, db: Session, rewrite_query
    ) -> list:
        # 解析历史聊天
        # 获取知识溯源配置
        ci_config = ConfigService.query_config_by_key(db=db, config_key="citation")
        citation_open = int(getattr(ci_config[0], "config_value", 0))
        
        if rewrite_query:
            query = rewrite_query
        else:
            query = request.retrival_params.user_query  # 当没有问题改写的时候，这里还是用户的原问题。
        messages = []
        CONTEXT_PROMPT_TS = """
                            你是一个专业的知识助手，你的任务是基于知识库内容来回答用户的问题，标注知识库的引用编号index，确保答案权威且可溯源。
                            ⚠️ 注意事项：  
                            1. **引用标注**：每一句包含知识来源的陈述都必须标注引用，引用严格按照标注格式，格式为[citation:1]（例如：太阳系有8颗行星 [citation:1]）。
                            2. **必须回答问题**：不输出任何无关内容。只在最终回答中根据知识库内容添加正确的标注格式。
                            3. **合并引用标注**：如果知识库中有多个片段支持同一句话的回答点，应合并标注（例如：月球轨道为椭圆[citation:1,2,3]）。  
                            4.**引用编号必须是知识库片段的引用编号**,不得凭空引用或捏造引用编号，只要统一标注引用编号，无需拆分知识库内容为多个子编号，不要引用知识库内容中的编号。
                            5. 若问题超出知识库范围，请根据自己的知识做补充。
                            ---
                            #知识库信息:
                            {chunk_content}
                            #用户问题:
                            {question}"""
        CONTEXT_PROMPT = """
                        你是一个AI问答助手，基于参考资料回答问题。
                        #知识库信息:
                        {chunk_content}
                        #用户问题:
                        {question}
                        """
        # logger.info(f"system_prompts:{request.system_prompts}")
        if request.system_prompts:
            messages.append({"role": "system", "content": request.system_prompts})
        talk_info = ChatConversationService.check_talk_info_history(
            db=db, conversation_id=request.conversation_id, type=type
        )

        if len(talk_info) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-(request.history + 1) : -1]
        else:
            chatbot = talk_info

        for idx, conversation in enumerate(chatbot):  # 循环遍历聊天记录
            # 存在模型消息，添加到消息列表中
            if conversation["user"] and conversation["assistant"]["content"] != "":
                messages.append({"role": "user", "content": conversation["user"]})

            else:
                pass
            if (
                conversation["assistant"]
                and conversation["assistant"] != "'[]'"
                and conversation["assistant"]["content"] != ""
            ):
                # LogUtil.info(f"conversation['assistant']:--{conversation['assistant']}")
                messages.append({"role": "assistant", "content": conversation["assistant"]["content"]})
            else:
                pass
        if chunk_content != "":
            if request.model_uid in model_list and citation_open == 1:  # 有溯源过程
                content = CONTEXT_PROMPT_TS.format(chunk_content=chunk_content, question=query)
                messages.append({"role": "user", "content": content})
            else:  # 无溯源过程
                content = CONTEXT_PROMPT.format(chunk_content=chunk_content, question=query)
                messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": query})

        return messages

    def parse_messages_trace(
        self,
        request: ChatCompletionRequestParams_v1,
        chunk_content,
        type,
        model_list,
        db: Session,
        rewrite_query,
        citation_open,
    ) -> list:
        # 解析历史聊天
        if rewrite_query:
            query = rewrite_query
        else:
            query = request.retrival_params.user_query  # 当没有问题改写的时候，这里还是用户的原问题。
        messages = []
        CONTEXT_PROMPT_TS = """
                            你是一个专业的知识助手，你的任务是基于知识库内容来回答用户的问题，标注知识库的引用编号index，确保答案权威且可溯源。
                            ⚠️ 注意事项：  
                            1. **引用标注**：每一句包含知识来源的陈述都必须标注引用，引用严格按照标注格式，格式为[citation:1]（例如：太阳系有8颗行星 [citation:1]）。
                            2. **必须回答问题**：不输出任何无关内容。只在最终回答中根据知识库内容添加正确的标注格式。
                            3. **合并引用标注**：如果知识库中有多个片段支持同一句话的回答点，应合并标注（例如：月球轨道为椭圆[citation:1,2,3]）。  
                            4.**引用编号必须是知识库片段的引用编号**,不得凭空引用或捏造引用编号，只要统一标注引用编号，无需拆分知识库内容为多个子编号，不要引用知识库内容中的编号。
                            5. 若问题超出知识库范围，请根据自己的知识做补充。
                            ---
                            #知识库信息:
                            {chunk_content}
                            #用户问题:
                            {question}"""
        CONTEXT_PROMPT = """
                        你是一个AI问答助手，基于参考资料回答问题。
                        #知识库信息:
                        {chunk_content}
                        #用户问题:
                        {question}
                        """
        # logger.info(f"system_prompts:{request.system_prompts}")
        if request.system_prompts:
            messages.append({"role": "system", "content": request.system_prompts})
        talk_info = ChatConversationService.check_talk_info_history(
            db=db, conversation_id=request.conversation_id, type=type
        )

        if len(talk_info) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-(request.history + 1) : -1]
        else:
            chatbot = talk_info

        for idx, conversation in enumerate(chatbot):  # 循环遍历聊天记录
            # 存在模型消息，添加到消息列表中
            if conversation["user"] and conversation["assistant"]["content"] != "":
                messages.append({"role": "user", "content": conversation["user"]})

            else:
                pass
            if (
                conversation["assistant"]
                and conversation["assistant"] != "'[]'"
                and conversation["assistant"]["content"] != ""
            ):
                # LogUtil.info(f"conversation['assistant']:--{conversation['assistant']}")
                messages.append({"role": "assistant", "content": conversation["assistant"]["content"]})
            else:
                pass
        if chunk_content != "":
            if request.model_uid in model_list and citation_open == 1:  # 有溯源过程
                content = CONTEXT_PROMPT_TS.format(chunk_content=chunk_content, question=query)
                messages.append({"role": "user", "content": content})
            else:  # 无溯源过程
                content = CONTEXT_PROMPT.format(chunk_content=chunk_content, question=query)
                messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": query})

        return messages

    def stream_chat_file(
        self, request: ChatCompletionRequestParams_v1, db: Session, chunk_content, type, model_list
    ) -> ChatCompletion:
        messages = self.parse_messages_file(
            db=db, request=request, chunk_content=chunk_content, type=type, model_list=model_list
        )
        # logger.info(
        #     "stream_chat_file历史messages: 类型=%s, 长度=%d",
        #     type(messages).__name__,
        #     len(messages) if hasattr(messages, "__len__") else "N/A",
        # )
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            stream=True,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
        )
        return completion_stream

    def parse_messages_file(
        self, request: ChatCompletionRequestParams_v1, chunk_content, type, model_list, db: Session
    ) -> list:
        # 解析历史聊天
        # 获取知识溯源配置
        ci_config = ConfigService.query_config_by_key(db=db, config_key="citation")
        citation_open = int(getattr(ci_config[0], "config_value", 0))
        
        messages = []

        CONTEXT_PROMPT_TS = """你是一个专业的知识助手，你的任务是基于知识库内容来回答用户的问题，标注知识库的引用编号index，确保答案权威且可溯源。
⚠️ 注意事项：  
1. **引用标注**：每一句包含知识来源的陈述都必须标注引用，引用严格按照标注格式，格式为[citation:1]（例如：太阳系有8颗行星 [citation:1]）。
2. **必须回答问题**：不输出任何思考、推理、分析或无关内容。思考阶段不输出任何"citation"文字，只在最终回答中根据知识库内容添加正确的标注格式。
3. **合并引用标注**：如果知识库中有多个片段支持同一句话的回答点，应合并标注（例如：月球轨道为椭圆[citation:1,2,3]）。  
4.**引用编号必须是知识库片段的引用编号**,不得凭空引用或捏造引用编号，只要统一标注引用编号，无需拆分知识库内容为多个子编号，不要引用知识库内容中的编号。
5. 若问题超出知识库范围，请根据自己的知识做补充。  
---
## 知识库信息  
{chunk_content}  
---
## 用户问题  
{question}"""
        CONTEXT_PROMPT = """你是一个AI问答助手，基于参考资料回答问题。
                                    ## 知识库信息  
                                    {chunk_content}  
                                    ---
                                    ## 用户问题  
                                    {question}"""
        # logger.info(f"system_prompts:{request.system_prompts}")
        if request.system_prompts:
            messages.append({"role": "system", "content": request.system_prompts})
        talk_info = ChatConversationService.check_talk_info_history(
            db=db, conversation_id=request.conversation_id, type=type
        )

        if len(talk_info) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-(request.history + 1) : -1]
        else:
            chatbot = talk_info

        for idx, conversation in enumerate(chatbot):  # 循环遍历聊天记录
            # 存在模型消息，添加到消息列表中
            if conversation["user"] and conversation["assistant"]["content"] != "":
                messages.append({"role": "user", "content": conversation["user"]})

            else:
                pass
            if (
                conversation["assistant"]
                and conversation["assistant"] != "'[]'"
                and conversation["assistant"]["content"] != ""
            ):
                # LogUtil.info(f"conversation['assistant']:--{conversation['assistant']}")
                messages.append({"role": "assistant", "content": conversation["assistant"]["content"]})
            else:
                pass
        if chunk_content != "":
            if request.model_uid in model_list and citation_open == 1:  # 有溯源过程
                content = CONTEXT_PROMPT_TS.format(
                    chunk_content=chunk_content, question=request.retrival_params.user_query
                )
                messages.append({"role": "user", "content": content})
            else:  # 无溯源过程
                content = CONTEXT_PROMPT.format(
                    chunk_content=chunk_content, question=request.retrival_params.user_query
                )
                messages.append({"role": "user", "content": content})
        else:
            messages.append({"role": "user", "content": request.retrival_params.user_query})

        return messages

    def stream_chat_with_penalty(self, request: ChatCompletionRequestParams) -> ChatCompletion:
        messages = self.parse_messages(request=request)
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            top_p=request.top_p,
            presence_penalty=request.presence_penalty,
            frequency_penalty=request.frequency_penalty,
            stream=True,
        )
        return completion_stream

    async def chunk_chat_with_penalty(self, request: ChatCompletionRequestParams) -> ChatCompletion:
        messages = self.parse_messages(request=request)
        completion = await self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            temperature=request.temperature,
            max_tokens=request.max_token_length,
            top_p=request.top_p,
            stream=False,
        )
        return completion.choices[0].message.content

    def rewrite_question(self, db, request, retrival_params, type=None):
        """
        重写用户问题
        :param db: 数据库连接
        :param request: 请求对象
        :param retrival_params: 检索参数对象
        :param type: 类型标识
        :return: 重写后的问题
        """
        try:
            # 初始化LLM服务
            rewritten_question = ""
            question_context = ""
            # 获取对话历史
            talk_info = ChatConversationService.check_talk_info_history(
                db=db, conversation_id=request.conversation_id, type=type
            )
            # 处理对话历史，根据需要截断
            if len(talk_info) > request.history:
                # 记录多于指定历史轮数量，进行截断
                chatbot = talk_info[-(request.history) :]
            else:
                chatbot = talk_info
            # 构建对话上下文
            for conversation in chatbot:
                # 添加用户问题
                if conversation.get("user"):
                    question_context += f"user_question：{conversation['user']}\n"
                if conversation.get("type") != 1:  # type=1说明没有模型回答直接返回的切片列表
                    # 添加模型回答
                    if conversation.get("assistant", {}).get("content", ""):
                        question_context += f"answer：{conversation['assistant']['content']}\n"
            question_prompt_template = f"""no think,不要思考，你是一个问题优化助手，帮助用户将不完整或含糊的问题改写为完整明确的问题。
            1.明确用户问题中缺失的核心指代对象、代词或条件，若上下文明确指向某一特定主体，需将该主体补充进问题中，避免泛化提问。
            2.若问题中存在指代歧义、代词缺失或条件缺失，需依据上下文补全关键信息，生成完整且指向明确的问题；若问题本身完整且上下文无额外补充信息，则保留原问题。
            3.回答仅输出改进后的用户问题，无需额外追问或列举示例选项，不要输出任何推理过程。
            4.若问题完整，输出用户原问题
            用户对话上下文历史：{question_context}
            用户的问题：{retrival_params.user_query}
            回答仅输出改进后的用户问题。
            重新生成的问题：
            """
            # 调用LLM服务进行问题重写 - 修复消息格式
            messages = [
                {"role": "system", "content": "你是一个问题优化助手"},
                {"role": "user", "content": question_prompt_template},
            ]

            # 调用LLM服务进行问题重写
            logger.info("原始用户问题: {}", getattr(retrival_params, "user_query", ""))

            completion = self.llm_model_client.chat.completions.create(
                model=request.model_uid,
                messages=messages,
                temperature=request.temperature,
                max_tokens=3000,
                stream=False,
                timeout=120,
            )

            rewritten_question = completion.choices[0].message.content
            rewritten_question = re.sub(r"<think>[\s\S]*?</think>", "", rewritten_question).strip()
            logger.info("重写后用户问题: {}", rewritten_question)

            return rewritten_question
        except Exception as e:
            logger.error(
                f"重写问题失败: model_uid={getattr(request, 'model_uid', None)}, "
                f"conversation_id={getattr(request, 'conversation_id', None)}, error={e!r}"
            )

            # 回退为原始问题
            return getattr(retrival_params, "user_query", "") or ""

    def multimodel_stream_chat(self, request: Multimodel_ChatParams, db: Session, type) -> ChatCompletion:
        messages = self.multimodelparse_messages_vl(db=db, request=request, type=type)
        completion_stream = self.async_llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=messages,
            stream=True,
        )
        return completion_stream

    def multimodel_chunk_chat(self, request: Multimodel_ChatParams, db: Session, type) -> ChatCompletion:
        completion_chunk = self.llm_model_client.chat.completions.create(
            model=request.model_uid,
            messages=[
                {"role": "system", "content": f"{ApiConfig.forbiddin_word_prompt}"},
                {"role": "user", "content": request.user_query},
            ],
            stream=False,
        )
        logger.info(completion_chunk)
        return completion_chunk.choices[0].message.content

    def multimodelparse_messages_vl(self, request: Multimodel_ChatParams, type, db: Session) -> list:
        # 解析历史聊天
        messages = []

        messages.append({"role": "system", "content": f"{ApiConfig.detect_prompt}"})

        talk_info = ChatConversationService.check_talk_info_history(
            db=db, conversation_id=request.conversation_id, type=type
        )
        # LogUtil.info(f"talk_info:--{talk_info}")
        if len(talk_info) > request.history:  # 记录多于指定历史轮数量，侧进行记录截断
            chatbot = talk_info[-(request.history + 1) : -1]
        else:
            chatbot = talk_info
        for idx, conversation in enumerate(chatbot):  # 循环遍历聊天记录
            # 存在模型消息，添加到消息列表中
            if conversation["user"] and conversation["assistant"]["content"] != "":
                if "images" in conversation:
                    if len(conversation["images"]) > 0:
                        change_conversation = []
                        for i, image in enumerate(conversation["images"]):
                            change_conversation.append(urljoin(f"http://{MinioConfig.END_POINT}", image))
                        image_b64_img = []
                        for image in change_conversation:
                            # LogUtil.info(str(type(image)))
                            image_b64_img.append(self.encode_to_base64(image))
                        image_contents = [
                            {"type": "image_url", "image_url": {"url": f"data:image;base64,{b64_img}"}}
                            for b64_img in image_b64_img
                        ]
                        messages.append(
                            {
                                "role": "user",
                                "content": image_contents + [{"type": "text", "text": conversation["user"]}],
                            }
                        )
                else:
                    messages.append({"role": "user", "content": conversation["user"]})
            else:
                pass
            if (
                conversation["assistant"]
                and conversation["assistant"] != "'[]'"
                and conversation["assistant"]["content"] != ""
            ):
                # LogUtil.info(f"conversation['assistant']:--{conversation['assistant']}")
                messages.append({"role": "assistant", "content": conversation["assistant"]["content"]})
            else:
                pass
        # LogUtil.log_json(
        #     describe="->实际输入LLM对话记录",
        #     kwargs=jsonable_encoder({"real_chat_messages": messages}),
        # )
        if request.images:
            image_b64_img = []
            request_images = []
            for i, image in enumerate(request.images):
                request_images.append(urljoin(f"http://{MinioConfig.END_POINT}", image))
            for image in request_images:
                # LogUtil.info(str(type(image)))
                image_b64_img.append(self.encode_to_base64(image))
            image_contents = [
                {"type": "image_url", "image_url": {"url": f"data:image;base64,{b64_img}"}} for b64_img in image_b64_img
            ]
            messages.append(
                {
                    "role": "user",
                    "content": image_contents + [{"type": "text", "text": request.user_query}],
                }
            )
        else:
            messages.append({"role": "user", "content": request.user_query})
        return messages


if __name__ == "__main__":
    openAILLMService = OpenAILLMService(model_uid="glm4-chat")
    response_content = openAILLMService.chat_completion(
        request=ChatCompletionRequestParams(
            question="如何学习python编程",
            system_prompts="",
            chatbot=[],
            history=3,
            max_token_length=4096,
            temperature=0.8,
            model_uid="glm4-chat",
        )
    )
    print("test...")
    print(f"response_content: {response_content}")
    a = {
        "model_uid": "glm4-chat",
        "system_prompts": "You are a helpful assistant,",
        "chatbot": [
            {"user": "你好", "assistant": "你好👋！有什么可以帮助你的吗？"},
            {
                "user": "介绍你自己",
                "assistant": "你好，我是一个名为 ChatGLM 的人工智能助手。我基于清华大学 KEG 实验室和智谱 AI 公司于 2024 年共同训练的语言模型 GLM-4 开发而成。我的任务是针对用户的问题和要求提供适当的答复和支持。",
            },
            {
                "user": "今天天气如何",
                "assistant": "很抱歉，我无法提供实时信息，包括今天的天气情况。要获取最新的天气信息，你可以查看当地的天气预报或者使用天气应用程序来了解。",
            },
        ],
        "question": "你现在会什么",
        "history": 3,
        "max_tokens": 4096,
        "temperature": 0.8,
    }
