#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Union
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime

Base = declarative_base()

class AccountToken_Model(Base):
    __tablename__ = TableConfig.ACC_TOKEN_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    account_id = Column(String(100))
    token = Column(String(300))
    refresh_token = Column(String(300))
    create_time = Column(DateTime)
    update_time = Column(DateTime)

