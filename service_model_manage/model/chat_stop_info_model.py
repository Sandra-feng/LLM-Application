#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime,Text
from sqlalchemy.dialects.mysql import MEDIUMTEXT


Base = declarative_base()

class ChatStopInfo_Model(Base):
    __tablename__ = TableConfig.CHAT_STOP_INFO_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    conversation_id = Column(String(100))
    talk_id = Column(String(100))
    account_id = Column(String(100))
    type = Column(Integer)
    status = Column(Integer,default=1,nullable=False)
    talk_num = Column(Integer, default=0, nullable=False)
