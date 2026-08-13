#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime,Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT


Base = declarative_base()

class ChatInfo_Model(Base):
    __tablename__ = TableConfig.CHAT_INFO_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    conversation_id = Column(String(100))
    talk_id = Column(String(100))
    token = Column(MEDIUMTEXT)
    account_id = Column(String(100))
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    status = Column(Integer,default=1,nullable=False)
    talk_num = Column(Integer, default=0, nullable=False)
    talk_attribute = Column(Integer, default=0, nullable=False)
    type = Column(Integer)
    model_id = Column(String(100))
    ag_id = Column(String(100))
    kb_id = Column(String(100))

class Question_Model(Base):
    __tablename__ = TableConfig.QUESTION_TABLE
    talk_id = Column(String(100),primary_key=True)
    question = Column(MEDIUMTEXT)



