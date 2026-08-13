import json
import time
from typing import Optional

from bson import ObjectId
from loguru import logger
from sqlalchemy import and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import Session

from base_configs.mongodb_config import CollectionConfig
from base_utils.mongodb_util import MongodbUtil
from service_model_manage.base_utils.mysql_util import query2dict, quick_sort
from service_model_manage.base_utils.snow_util import generate_unique_id
from service_model_manage.model.chat_info_model import ChatInfo_Model, Question_Model
from service_model_manage.model.chat_stop_info_model import ChatStopInfo_Model
from service_model_manage.model.mem_chat_model import MemberChat_Model


# logger = loguru logger (auto-migrated)
class ChatConversationService:
    datacenter_id = 1
    worker_id = 1

    @staticmethod
    def local_time():
        local_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time()))
        return local_time

    @staticmethod
    def check_conversation_id(db: Session, conversation_id: str, account_id: str):
        conversation_info = (
            db.query(MemberChat_Model)
            .filter(
                MemberChat_Model.conversation_id == conversation_id,
                MemberChat_Model.account_id == account_id,
                MemberChat_Model.status == 1,
            )
            .first()
        )
        if conversation_info:
            return True
        else:
            return False

    @staticmethod
    def creat_conversation_id_v1(db: Session, account_id: str, type: int, model_id: str, kb_id: str, ag_id: str):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花conversation_id
        conversation_id = generate_unique_id(
            "CONVER_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )

        db_config = MemberChat_Model(
            conversation_id=conversation_id,
            account_id=account_id,
            model_id=model_id,
            type=type,
            kb_id=kb_id,
            ag_id=ag_id,
            create_time=create_time,
            update_time=update_time,
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

        return conversation_id

    @staticmethod
    def creat_conversation_id(db: Session, account_id: str):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花conversation_id
        conversation_id = generate_unique_id(
            "CONVER_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )

        db_config = MemberChat_Model(
            conversation_id=conversation_id, account_id=account_id, create_time=create_time, update_time=update_time
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

        return conversation_id

    @staticmethod
    def save_talk_data(db: Session, account_id: str, conversation_id: str, token: str, question: str):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花talk_id
        talk_id = generate_unique_id(
            "TALK_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )
        token_data = '{"user":"' + question + '","assistant":"' + token + '"}'
        db_config = ChatInfo_Model(
            conversation_id=conversation_id,
            talk_id=talk_id,
            account_id=account_id,
            token=token_data,
            create_time=create_time,
            update_time=update_time,
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

    @staticmethod
    def save_talk_data_v1(
        db: Session,
        account_id: str,
        conversation_id: str,
        token: str,
        question: str,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
        retrival_info,
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花talk_id
        talk_id = generate_unique_id(
            "TALK_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )
        data = {"user": question, "assistant": {"content": token, "retrival_info": retrival_info}, "type": 0}
        token_data = json.dumps(data)
        db_config = ChatInfo_Model(
            conversation_id=conversation_id,
            talk_id=talk_id,
            account_id=account_id,
            token=token_data,
            type=type,
            model_id=model_id,
            ag_id=ag_id,
            kb_id=kb_id,
            create_time=create_time,
            update_time=update_time,
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

    @staticmethod
    def save_talk_history_v1(
        db: Session,
        account_id: str,
        conversation_id: str,
        data: dict,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花talk_id
        talk_id = generate_unique_id(
            "TALK_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )
        # data = {"user": question, "assistant": {"content": token, "retrival_info": retrival_info}, "type": 0}
        token_data = json.dumps(data)
        db_config = ChatInfo_Model(
            conversation_id=conversation_id,
            talk_id=talk_id,
            account_id=account_id,
            token=token_data,
            type=type,
            model_id=model_id,
            ag_id=ag_id,
            kb_id=kb_id,
            create_time=create_time,
            update_time=update_time,
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

    @staticmethod
    def save_talk_data_file(
        db: Session,
        account_id: str,
        conversation_id: str,
        prompt: str,
        think: str,
        think_time: float,
        token: str,
        images: list,
        question: str,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
        talk_id: str,
        retrival_info,
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time
        talk_num = 0
        if talk_id == "":
            # 生成唯一雪花talk_id
            talk_id = generate_unique_id(
                "TALK_",
                datacenter_id=ChatConversationService.datacenter_id,
                worker_id=ChatConversationService.worker_id,
            )
            data = {
                "prompt": prompt,
                "user": question,
                "images": images,
                "assistant": {
                    "content": token,
                    "think": think,
                    "think_time": think_time,
                    "retrival_info": retrival_info,
                },
                "type": 0,
            }
            token_data = json.dumps(data)
            db_config = ChatInfo_Model(
                conversation_id=conversation_id,
                talk_id=talk_id,
                account_id=account_id,
                token=token_data,
                type=type,
                model_id=model_id,
                ag_id=ag_id,
                kb_id=kb_id,
                create_time=create_time,
                update_time=update_time,
            )

            db.add(db_config)

            db.commit()

            db.refresh(db_config)
        else:
            resource_data = db.query(ChatInfo_Model).filter(ChatInfo_Model.talk_id == talk_id).all()
            talk_num = len(resource_data)
            data = {
                "prompt": prompt,
                "user": question,
                "images": images,
                "assistant": {
                    "content": token,
                    "think": think,
                    "think_time": think_time,
                    "retrival_info": retrival_info,
                },
                "type": 0,
            }
            token_data = json.dumps(data)
            db_config = ChatInfo_Model(
                conversation_id=conversation_id,
                talk_id=talk_id,
                account_id=account_id,
                token=token_data,
                type=type,
                model_id=model_id,
                ag_id=ag_id,
                kb_id=kb_id,
                talk_num=talk_num,
                create_time=create_time,
                update_time=update_time,
            )

            db.add(db_config)

            db.commit()

            db.refresh(db_config)

        return talk_id, talk_num

    @staticmethod
    def save_talk_data_file_stop(
        db: Session, account_id: str, conversation_id: str, type: int, talk_id: str, talk_num: int
    ):
        # 设置时间
        db_config = ChatStopInfo_Model(
            conversation_id=conversation_id,
            talk_id=talk_id,
            account_id=account_id,
            type=type,
            talk_num=talk_num,
        )
        db.add(db_config)
        db.commit()
        db.refresh(db_config)

    def save_talk_data_retrival(
        db: Session,
        account_id: str,
        conversation_id: str,
        token: list,
        question: str,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花talk_id
        talk_id = generate_unique_id(
            "TALK_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )
        data = {"user": question, "assistant": token, "type": 1}
        token_data = json.dumps(data)
        db_config = ChatInfo_Model(
            conversation_id=conversation_id,
            talk_id=talk_id,
            account_id=account_id,
            token=token_data,
            type=type,
            model_id=model_id,
            ag_id=ag_id,
            kb_id=kb_id,
            create_time=create_time,
            update_time=update_time,
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

    @staticmethod
    def check_talk_delete(db: Session, conversation_id: str):
        update_time = ChatConversationService.local_time()

        db.query(ChatInfo_Model).filter(
            ChatInfo_Model.conversation_id == conversation_id, ChatInfo_Model.status == 1
        ).update({ChatInfo_Model.status: 0, ChatInfo_Model.update_time: update_time})
        db.commit()

        return "ok"

    @staticmethod
    def chat_workflow_delete(db: Session, conversation_id: str):
        update_time = ChatConversationService.local_time()

        results = db.query(MemberChat_Model).filter(MemberChat_Model.workflow_conversation_id == conversation_id).all()
        seb_conversation_ids = []
        if len(results) != 0:
            for result in results:
                seb_conversation_ids.append(result.conversation_id)

        if len(seb_conversation_ids) != 0:
            for seb_conversation_id in seb_conversation_ids:
                db.query(ChatInfo_Model).filter(
                    ChatInfo_Model.conversation_id == seb_conversation_id, ChatInfo_Model.status == 1
                ).update({ChatInfo_Model.status: 0, ChatInfo_Model.update_time: update_time})

        db.query(ChatInfo_Model).filter(
            ChatInfo_Model.conversation_id == conversation_id, ChatInfo_Model.status == 1
        ).update({ChatInfo_Model.status: 0, ChatInfo_Model.update_time: update_time})
        db.commit()

        return "ok"

    @staticmethod
    def check_conversation_delete(db: Session, conversation_id: str):
        update_time = ChatConversationService.local_time()
        db.query(MemberChat_Model).filter(
            MemberChat_Model.conversation_id == conversation_id, MemberChat_Model.status == 1
        ).update({MemberChat_Model.status: 0, MemberChat_Model.update_time: update_time})
        db.commit()

        return "ok"

    @staticmethod
    def creat_chat(db: Session, account_id: str, type: int, model_id: str, kb_id: str, ag_id: str, creat: str):
        token = []
        time_info = {}
        conv_info = []
        conversation_info = (
            db.query(MemberChat_Model)
            .filter(
                MemberChat_Model.account_id == account_id,
                MemberChat_Model.type == type,
                MemberChat_Model.model_id == model_id,
                MemberChat_Model.ag_id == ag_id,
                MemberChat_Model.kb_id == kb_id,
                MemberChat_Model.status == 1,
            )
            .all()
        )
        if conversation_info:
            history_data = query2dict(conversation_info, MemberChat_Model)
            quick_sort(history_data, 0, len(history_data) - 1, "create_time")
            for data in history_data:
                conversation_id = data["conversation_id"]
                time_info[conversation_id] = data["create_time"]
                token.append(conversation_id)
                token = list(dict.fromkeys(token))
            if creat != "":
                conversation_id = ChatConversationService.creat_conversation_id_v1(
                    db=db, account_id=account_id, type=type, model_id=model_id, kb_id=kb_id, ag_id=ag_id
                )
                token.insert(0, conversation_id)
        else:
            logger.info("->创建对话id列表")
            conversation_id = ChatConversationService.creat_conversation_id_v1(
                db=db, account_id=account_id, type=type, model_id=model_id, kb_id=kb_id, ag_id=ag_id
            )
            logger.info("->创建对话id列表成功")
            token.append(conversation_id)
        for conv_id in token:
            history = ChatConversationService.check_talk_info_history(db=db, conversation_id=conv_id, type=type)
            if not history:
                conv_info.append({"conversation_id": conv_id})
                update_time = ChatConversationService.local_time()
                db.query(MemberChat_Model).filter(
                    MemberChat_Model.conversation_id == conv_id, MemberChat_Model.status == 1
                ).update({MemberChat_Model.create_time: update_time})
                db.commit()
            else:
                history[0]["create_time"] = time_info[conv_id]
                history[0]["conversation_id"] = conv_id
                conv_info.append(history[0])
        return conv_info

    @staticmethod
    def create_text_to_image_chat(
        db: Session, account_id: str, type: int, model_id: str, kb_id: str, ag_id: str, create: str
    ):
        token = []
        time_info = {}
        conv_info = []

        # 先从MYSQL的mem_chat表中查询该用户的所有对话记录
        conversation_info = (
            db.query(MemberChat_Model)
            .filter(
                MemberChat_Model.account_id == account_id,
                MemberChat_Model.type == type,
                MemberChat_Model.model_id == model_id,
                MemberChat_Model.ag_id == ag_id,
                MemberChat_Model.kb_id == kb_id,
                MemberChat_Model.status == 1,
            )
            .all()
        )

        # 再对对话记录进行处理
        if conversation_info:
            history_data = query2dict(conversation_info, MemberChat_Model)
            quick_sort(history_data, 0, len(history_data) - 1, "update_time")
            for data in history_data:
                conversation_id = data["conversation_id"]
                time_info[conversation_id] = data["update_time"]
                token.append(conversation_id)
                # 对token中的对话id进行重排
                token = list(dict.fromkeys(token))
            # 判断是否是创建新对话
            if create != "":
                conversation_id = ChatConversationService.creat_conversation_id_v1(
                    db=db, account_id=account_id, type=type, model_id=model_id, kb_id=kb_id, ag_id=ag_id
                )
                # 最新的对话记录
                token.insert(0, conversation_id)

        # 没有对话记录，重建新对话
        else:
            logger.info("->创建新对话")
            conversation_id = ChatConversationService.creat_conversation_id_v1(
                db=db, account_id=account_id, type=type, model_id=model_id, kb_id=kb_id, ag_id=ag_id
            )
            # 最新的对话记录
            logger.info("->创建对话成功")
            token.append(conversation_id)

        for conv_id in token:
            # 获取每个对话的所有历史会话记录
            history = ChatConversationService.check_talk_info_history(db=db, conversation_id=conv_id, type=type)

            if history == []:
                conv_info.append({"conversation_id": conv_id})
                update_time = ChatConversationService.local_time()
                db.query(MemberChat_Model).filter(
                    MemberChat_Model.conversation_id == conv_id, MemberChat_Model.status == 1
                ).update({MemberChat_Model.create_time: update_time})
                db.commit()
            # 取所有会话记录中时间最早的那一条记录，添加create_time与conversation_id字段
            else:
                history[0]["create_time"] = time_info[conv_id]
                history[0]["conversation_id"] = conv_id
                conv_info.append(history[0])
        return conv_info

    @staticmethod
    def save_talk_data_image(
        db: Session,
        account_id: str,
        conversation_id: str,
        images: list,
        question: str,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
        talk_id: str,
        image: str = "",
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time
        talk_num = 0
        if talk_id == "":
            talk_id = generate_unique_id(
                "TALK_",
                datacenter_id=ChatConversationService.datacenter_id,
                worker_id=ChatConversationService.worker_id,
            )
            data = (
                {"user": question, "assistant": {"images": images}}
                if not image
                else {"user": question, "assistant": {"self_image": image, "images": images}}
            )
            token_data = json.dumps(data)
            db_config = ChatInfo_Model(
                conversation_id=conversation_id,
                talk_id=talk_id,
                account_id=account_id,
                token=token_data,
                type=type,
                model_id=model_id,
                ag_id=ag_id,
                kb_id=kb_id,
                create_time=create_time,
                update_time=update_time,
            )

            db.add(db_config)
            db.commit()
            db.refresh(db_config)

        else:
            resource_data = db.query(ChatInfo_Model).filter(ChatInfo_Model.talk_id == talk_id).all()
            talk_num = len(resource_data)
            data = (
                {"user": question, "assistant": {"images": images}}
                if not image
                else {"user": question, "assistant": {"self_image": image, "images": images}}
            )
            token_data = json.dumps(data)
            db_config = ChatInfo_Model(
                conversation_id=conversation_id,
                talk_id=talk_id,
                account_id=account_id,
                token=token_data,
                type=type,
                model_id=model_id,
                ag_id=ag_id,
                kb_id=kb_id,
                talk_num=talk_num,
                create_time=create_time,
                update_time=update_time,
            )

            db.add(db_config)
            db.commit()
            db.refresh(db_config)

        return talk_id, talk_num

    @staticmethod
    def check_talk_list(db: Session, account_id: str, type: int, model_id: str, kb_id: str, ag_id: str):
        token = []
        conversation_info = (
            db.query(MemberChat_Model)
            .filter(
                MemberChat_Model.account_id == account_id,
                MemberChat_Model.type == type,
                MemberChat_Model.model_id == model_id,
                MemberChat_Model.ag_id == ag_id,
                MemberChat_Model.kb_id == kb_id,
                MemberChat_Model.status == 1,
            )
            .all()
        )
        if conversation_info != []:
            history_data = query2dict(conversation_info, MemberChat_Model)
            quick_sort(history_data, 0, len(history_data) - 1, "create_time")
            for data in history_data:
                conversation_id = data["conversation_id"]
                token.append(conversation_id)
                token = list(dict.fromkeys(token))
        else:
            conversation_id = ChatConversationService.creat_conversation_id_v1(
                db=db, account_id=account_id, type=type, model_id=model_id, kb_id=kb_id, ag_id=ag_id
            )
            token.append(conversation_id)
        return token

    def check_talk_list_prompt(db: Session, account_id: str, type: int, model_id: str, kb_id: str, ag_id: str):
        token = []
        conversations_info = (
            db.query(MemberChat_Model)
            .filter(
                MemberChat_Model.account_id == account_id,
                MemberChat_Model.type == type,
                MemberChat_Model.model_id == model_id,
                MemberChat_Model.ag_id == ag_id,
                MemberChat_Model.kb_id == kb_id,
                MemberChat_Model.status == 1,
            )
            .all()
        )
        if conversations_info != []:
            for conversation_info in conversations_info:
                # LogUtil.info(f"对话信息:{str(conversation_info)}")
                # LogUtil.info(f"对话id信息:{str(conversation_info.conversation_id)}")
                conversation_id = conversation_info.conversation_id
                res = ChatConversationService.check_talk_delete(
                    db=db, conversation_id=conversation_info.conversation_id
                )
        else:
            conversation_id = ChatConversationService.creat_conversation_id_v1(
                db=db, account_id=account_id, type=type, model_id=model_id, kb_id=kb_id, ag_id=ag_id
            )
        token.append(conversation_id)
        return token

    @staticmethod
    def check_talk_info(db: Session, conversation_id: str):
        token = []
        conversation_info = (
            db.query(ChatInfo_Model)
            .filter(
                ChatInfo_Model.conversation_id == conversation_id, ChatInfo_Model.status == 1, ChatInfo_Model.type == 0
            )
            .all()
        )

        history_data = query2dict(conversation_info, ChatInfo_Model)
        # quick_sort(history_data, 0, len(history_data) - 1, "create_time")
        for data in history_data:
            # 预处理JSON字符串，替换掉非法的控制字符或确保它们被正确转义
            # def clean_json_string(json_str):
            #     # 使用正则表达式移除或转义可能导致问题的控制字符
            #     import re
            #     def replace_with_escape(match):
            #         char = match.group(0)
            #         if char == '\n':
            #             return '\\n'
            #         elif char == '\t':
            #             return '\\t'
            #         elif char == '\r':
            #             return '\\r'
            #         # 可以添加更多条件来处理其他控制字符
            #         else:
            #             return ''
            #
            #     # 替换掉可能导致问题的控制字符
            #     json_str = re.sub(r'[\n\t\r]', replace_with_escape, json_str)
            #     return json_str

            # cleaned_json_str = clean_json_string(data['token'])
            cleaned_json_str = data["token"]
            token.append(json.loads(cleaned_json_str))
        return token

    @staticmethod
    def check_talk_info_history(db: Session, conversation_id: str, type: Optional[int] = None):
        token = []
        conditions = [ChatInfo_Model.conversation_id == conversation_id, ChatInfo_Model.status == 1]

        # 如果 type 存在，则添加 type 条件
        if type is not None:
            conditions.append(ChatInfo_Model.type == type)

        # 使用 and_ 函数将所有条件组合起来
        query_conditions = and_(*conditions)

        # 执行查询
        conversation_info = db.query(ChatInfo_Model).filter(query_conditions).all()

        history_data = query2dict(conversation_info, ChatInfo_Model)

        for data in history_data:
            cleaned_json_str = data["token"]
            re_token = json.loads(cleaned_json_str)
            re_token["talk_id"] = data["talk_id"]
            token.append(re_token)
        return token

    @staticmethod
    def save_talk_data_agent(
        db: Session,
        account_id: str,
        conversation_id: str,
        token: str,
        question: str,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
        system_prompt: str,
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花talk_id
        talk_id = generate_unique_id(
            "TALK_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )
        data = {"prompt": system_prompt, "user": question, "assistant": {"content": token}, "type": type}
        token_data = json.dumps(data)

        db_config = ChatInfo_Model(
            conversation_id=conversation_id,
            talk_id=talk_id,
            account_id=account_id,
            token=token_data,
            type=type,
            model_id=model_id,
            ag_id=ag_id,
            kb_id=kb_id,
            create_time=create_time,
            update_time=update_time,
        )

        db.add(db_config)

        db.commit()

        db.refresh(db_config)

        return talk_id

    @staticmethod
    def task_query_id(task_name_dic: dict, account_id: str):
        kb_list = []
        tool_list = []
        if task_name_dic.get("kb_list") is not None:
            # 查询知识库列表
            for kb in task_name_dic["kb_list"]:
                kb_result = list(
                    MongodbUtil.query_docs_by_condition(
                        CollectionConfig.KB_COLLECTION, search_condition={"_id": ObjectId(kb)}
                    )
                )
                if len(kb_result) != 0:
                    for kb_id in kb_result:
                        kb_list.append(str(kb_id["_id"]))
                else:
                    kb_list.append("知识库ID不存在，请给出正确的知识库ID")
            task_name_dic["kb_list"] = kb_list
        if task_name_dic.get("tool_list") is not None:
            # 查询工具列表
            for tool in task_name_dic["tool_list"]:
                tool_result = list(
                    MongodbUtil.query_docs_by_condition(
                        CollectionConfig.TOOL_INFO_COLLECTION, search_condition={"_id": tool}
                    )
                )
                if len(tool_result) != 0:
                    for tool_id in tool_result:
                        tool_list.append(str(tool_id["_id"]))
                else:
                    tool_list.append("工具ID不存在，请给出正确的工具ID")
            task_name_dic["tool_list"] = tool_list
        return task_name_dic

    @staticmethod
    def prompt_params(params_dic: dict, prompt: str):
        if params_dic.get("prompt_params") is not None:
            param = params_dic["prompt_params"]
            for key, value in param.items():
                placeholder = "{{" + key + "}}"
                prompt = prompt.replace(placeholder, value)
        return prompt

    @staticmethod
    def update_talk_data(db: Session, talk_id: str, token_data: str, talk_num: int):
        update_time = ChatConversationService.local_time()

        resource_data = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.talk_id == talk_id, ChatInfo_Model.talk_num == talk_num)
            .first()
        )
        resource_data.update_time = update_time
        resource_data.token = token_data

        db.commit()

        db.refresh(resource_data)

    @staticmethod
    def update_talk_status(db: Session, talk_id: str, talk_num: int):
        update_time = ChatConversationService.local_time()

        resource_data = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.talk_id == talk_id, ChatInfo_Model.talk_num == talk_num)
            .first()
        )
        resource_data.status = 1
        resource_data.update_time = update_time

        db.commit()

        db.refresh(resource_data)

    @staticmethod
    def check_talk_status(db: Session, talk_id: str, talk_num: int):
        resource_data = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.talk_id == talk_id, ChatInfo_Model.talk_num == talk_num)
            .first()
        )
        talk_status = resource_data.status

        return talk_status

    @staticmethod
    def check_talk_stop_status(db: Session, talk_id: str, talk_num: int):
        resource_data = (
            db.query(ChatStopInfo_Model)
            .filter(ChatStopInfo_Model.talk_id == talk_id, ChatStopInfo_Model.talk_num == talk_num)
            .first()
        )
        talk_status = resource_data.status
        return talk_status

    @staticmethod
    def stop_talk(db: Session, talk_id: str, talk_num: int):
        update_time = ChatConversationService.local_time()

        resource_data = (
            db.query(ChatStopInfo_Model)
            .filter(ChatStopInfo_Model.talk_id == talk_id, ChatStopInfo_Model.talk_num == talk_num)
            .first()
        )
        resource_data.status = 3
        resource_data.update_time = update_time

        db.commit()

        db.refresh(resource_data)

    @staticmethod
    def delete_talk(db: Session, talk_id: str):
        update_time = ChatConversationService.local_time()

        resource_data = db.query(ChatInfo_Model).filter(ChatInfo_Model.talk_id == talk_id).first()
        resource_data.status = 0
        resource_data.update_time = update_time

        db.commit()

        db.refresh(resource_data)

    @staticmethod
    def check_talk_info_history_firstpage(db: Session, conversation_id: str, type: Optional[int] = None):
        token = []
        talk = {}
        conditions = [ChatInfo_Model.conversation_id == conversation_id, ChatInfo_Model.status == 1]

        # 如果 type 存在，则添加 type 条件
        if type is not None:
            conditions.append(ChatInfo_Model.type == type)

        # 使用 and_ 函数将所有条件组合起来
        query_conditions = and_(*conditions)

        # 执行查询
        conversation_info = db.query(ChatInfo_Model).filter(query_conditions).all()

        history_data = query2dict(conversation_info, ChatInfo_Model)
        # LogUtil.info(f"对话信息:{str(history_data)}")
        # quick_sort(history_data, 0, len(history_data) - 1, "create_time")
        for data in history_data:
            # 预处理JSON字符串，替换掉非法的控制字符或确保它们被正确转义
            def clean_json_string(json_str):
                # 使用正则表达式移除或转义可能导致问题的控制字符
                import re

                def replace_with_escape(match):
                    char = match.group(0)
                    if char == "\n":
                        return "\\n"
                    elif char == "\t":
                        return "\\t"
                    elif char == "\r":
                        return "\\r"
                    # 可以添加更多条件来处理其他控制字符
                    else:
                        return ""

                # 替换掉可能导致问题的控制字符
                json_str = re.sub(r"[\n\t\r]", replace_with_escape, json_str)
                return json_str

            cleaned_json_str = clean_json_string(data["token"])
            re_token = json.loads(cleaned_json_str)
            re_token["talk_num"] = data["talk_num"]
            re_token["talk_like"] = data["talk_attribute"]
            talk_id = data["talk_id"]
            if talk_id not in talk:
                talk[talk_id] = []
            talk[talk_id].append(re_token)
        result = [{"id": key, "content": value} for key, value in talk.items()]
        return result

    @staticmethod
    def like_talk(db: Session, talk_id: str, talk_num: int, like_status: int):
        update_time = ChatConversationService.local_time()

        resource_data = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.talk_id == talk_id, ChatInfo_Model.talk_num == talk_num)
            .first()
        )
        resource_data.talk_attribute = like_status
        resource_data.update_time = update_time

        db.commit()

        db.refresh(resource_data)

        resource_data = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.talk_id == talk_id, ChatInfo_Model.talk_num == talk_num)
            .first()
        )
        talk_like_status = resource_data.talk_attribute
        return talk_like_status

    @staticmethod
    async def update_talk_data_agent(db: Session, talk_id: str, token_data: str):
        update_time = ChatConversationService.local_time()
        resource_data = db.query(ChatInfo_Model).filter(ChatInfo_Model.talk_id == talk_id).first()
        resource_data.update_time = update_time
        resource_data.token = token_data
        db.commit()
        db.refresh(resource_data)

    @staticmethod
    def like_talk_review(db: Session, talk_id: str, talk_num: int, talk_review: str, answer_review_tag: list):
        update_time = ChatConversationService.local_time()
        resource_data = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.talk_id == talk_id, ChatInfo_Model.talk_num == talk_num, ChatInfo_Model.status == 1)
            .first()
        )
        resource_data.update_time = update_time
        token_data = json.loads(resource_data.token)
        token_data["talk_review"] = talk_review
        token_data["answer_review_tag"] = answer_review_tag
        resource_data.token = json.dumps(token_data)

        db.commit()

        db.refresh(resource_data)

        return token_data

    @staticmethod
    def export_chat_history(db: Session, conversation_id_list: list, talk_id_list: list):
        def clean_json_string(json_str):
            # 使用正则表达式移除或转义可能导致问题的控制字符
            import re

            def replace_with_escape(match):
                char = match.group(0)
                if char == "\n":
                    return "\\n"
                elif char == "\t":
                    return "\\t"
                elif char == "\r":
                    return "\\r"
                # 可以添加更多条件来处理其他控制字符
                else:
                    return ""

            # 替换掉可能导致问题的控制字符
            json_str = re.sub(r"[\n\t\r]", replace_with_escape, json_str)
            return json_str

        data_list = []
        if talk_id_list == []:
            for conversation_id in conversation_id_list:
                resource_data = (
                    db.query(ChatInfo_Model)
                    .filter(ChatInfo_Model.conversation_id == conversation_id, ChatInfo_Model.status == 1)
                    .all()
                )
                if resource_data != []:
                    history_data = query2dict(resource_data, ChatInfo_Model)
                    for data in history_data:
                        cleaned_json_str = clean_json_string(data["token"])
                        re_token = json.loads(cleaned_json_str)
                        data_dict = {}
                        data_dict["talk_account_id"] = data["account_id"]
                        data_dict["talk_content"] = re_token
                        data_dict["talk_model_id"] = data["model_id"]
                        data_dict["talk_attr"] = data["talk_attribute"]
                        data_dict["talk_review"] = data.get("talk_review", None)
                        data_dict["answer_review_tag"] = data.get("answer_review_tag", None)
                        data_list.append(data_dict)
            return data_list
        else:
            for talk_id in talk_id_list:
                for conversation_id in conversation_id_list:
                    resource_data = (
                        db.query(ChatInfo_Model)
                        .filter(
                            ChatInfo_Model.conversation_id == conversation_id,
                            ChatInfo_Model.talk_id == talk_id,
                            ChatInfo_Model.status == 1,
                        )
                        .all()
                    )
                    if resource_data != []:
                        history_data = query2dict(resource_data, ChatInfo_Model)
                        for data in history_data:
                            cleaned_json_str = clean_json_string(data["token"])
                            re_token = json.loads(cleaned_json_str)
                            data_dict = {}
                            data_dict["talk_account_id"] = data["account_id"]
                            data_dict["talk_content"] = re_token
                            data_dict["talk_model_id"] = data["model_id"]
                            data_dict["talk_attr"] = data["talk_attribute"]
                            data_dict["talk_review"] = data.get("talk_review", None)
                            data_dict["answer_review_tag"] = data.get("answer_review_tag", None)
                            data_list.append(data_dict)
            return data_list

    @staticmethod
    def new_talk_id(db: Session, talk_id: str):
        resource_data = db.query(ChatInfo_Model).filter(ChatInfo_Model.talk_id == talk_id).first()
        talk = resource_data.token

        return talk

    @staticmethod
    def insert_question1(db: Session, talk_id: str):
        # 查询数据库中是否存在与 talk_id 对应的记录
        existing_question = db.query(Question_Model).filter(Question_Model.talk_id == talk_id).first()

        if existing_question:
            # 数据已存在
            # 如果存在，返回查询到的记录
            return existing_question
        else:
            # 数据不存在
            existing_question = 0
            return existing_question

    @staticmethod
    def insert_question(db: Session, talk_id: str, question: str):
        # 查询数据库中是否存在与 talk_id 对应的记录
        existing_question = db.query(Question_Model).filter(Question_Model.talk_id == talk_id).first()

        if existing_question:
            # 数据已存在
            # 如果存在，返回查询到的记录
            return existing_question
        else:
            # 如果不存在，创建一个新的 Question_Model 实例
            new_question = Question_Model(talk_id=talk_id, question=question)
            # 将新实例添加到数据库会话
            db.add(new_question)
            # 提交会话，将数据保存到数据库
            db.commit()
            # 返回新插入的记录
            return new_question

    @staticmethod
    def query_question(db: Session, talk_id: str):
        # 查询指定 talk_id 的问题
        question = db.query(Question_Model).filter(Question_Model.talk_id == talk_id).first()
        return question

    @staticmethod
    def conversion_to_talk(db: Session, conversation_id: str):
        from sqlalchemy import desc

        # 查询 conversation_id 对应的所有数据，并按时间戳降序排序
        latest_talk = (
            db.query(ChatInfo_Model)
            .filter(ChatInfo_Model.conversation_id == conversation_id)
            .order_by(desc(ChatInfo_Model.create_time))  # 假设时间戳字段名为 created_at
            .first()
        )

        return latest_talk

    @staticmethod
    def query_talk_data_agent(db: Session, talk_id: str):
        resource_data = db.query(ChatInfo_Model).filter(ChatInfo_Model.talk_id == talk_id).first()

        return resource_data

    @staticmethod
    def save_workflow_talk_data_agent(
        db: Session,
        account_id: str,
        conversation_id: str,
        token: list,
        question: str,
        model_id: str,
        ag_id: str,
        kb_id: str,
        type: int,
        system_prompt: str,
    ):
        # 设置时间
        create_time = ChatConversationService.local_time()
        update_time = create_time

        # 生成唯一雪花talk_id
        talk_id = generate_unique_id(
            "TALK_", datacenter_id=ChatConversationService.datacenter_id, worker_id=ChatConversationService.worker_id
        )
        # data = {"user": question, "assistant": token, "type": type}
        # token_data = json.dumps(data)
        #
        # db_config = ChatInfo_Model(conversation_id=conversation_id, talk_id=talk_id,
        #                            account_id=account_id, token=token_data, type=type, model_id=model_id, ag_id=ag_id,
        #                            kb_id=kb_id,
        #                            create_time=create_time, update_time=update_time)
        #
        # db.add(db_config)
        #
        # db.commit()
        #
        # db.refresh(db_config)

        return talk_id

    # @staticmethod
    # def save_workflow_talk_data_agent_withtalkid(db: Session, account_id: str, conversation_id: str, token: list, question: str,
    #                                   model_id: str,
    #                                   ag_id: str, kb_id: str, type: int, system_prompt: str,talk_id:str):
    #     # 设置时间
    #     create_time = ChatConversationService.local_time()
    #     update_time = create_time
    #     if talk_id!=None and talk_id!="" and talk_id!='':
    #         talk_id = talk_id
    #         # 生成唯一雪花talk_id
    #
    #     else:
    #         talk_id = generate_unique_id('TALK_', datacenter_id=ChatConversationService.datacenter_id,
    #                                      worker_id=ChatConversationService.worker_id)
    #
    #     # data = {"user": question, "assistant": token, "type": type}
    #     # token_data = json.dumps(data)
    #     #
    #     # db_config = ChatInfo_Model(conversation_id=conversation_id, talk_id=talk_id,
    #     #                            account_id=account_id, token=token_data, type=type, model_id=model_id, ag_id=ag_id,
    #     #                            kb_id=kb_id,
    #     #                            create_time=create_time, update_time=update_time)
    #     #
    #     # db.add(db_config)
    #     #
    #     # db.commit()
    #     #
    #     # db.refresh(db_config)
    #
    #     return talk_id
    @staticmethod
    async def check_talk_stop_status1(db: AsyncSession, talk_id: str, talk_num: int):
        # 提交事务
        # await db.commit()

        # 查询数据
        result = await db.execute(
            select(ChatStopInfo_Model).filter(
                ChatStopInfo_Model.talk_id == talk_id, ChatStopInfo_Model.talk_num == talk_num
            )
        )
        resource_data = result.scalars().first()
        talk_status = resource_data.status if resource_data else None
        return talk_status
