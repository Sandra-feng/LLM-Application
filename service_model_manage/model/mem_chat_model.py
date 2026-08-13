#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Union
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime

Base = declarative_base()

class MemberChat_Model(Base):
    __tablename__ = TableConfig.MEM_CHAT_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    conversation_id = Column(String(100))
    account_id = Column(String(100))
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    status = Column(Integer,default=1,nullable=False)
    type = Column(Integer)
    model_id = Column(String(100))
    kb_id = Column(String(100))
    ag_id = Column(String(100))
    workflow_conversation_id = Column(String(100))
