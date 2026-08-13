#!/usr/bin/env python
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

from base_configs.mysql_config import TableConfig

Base = declarative_base()


class AccountToken_Model(Base):
    __tablename__ = TableConfig.ACC_TOKEN_TABLE
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    account_id = Column(String(100))
    token = Column(String(300))
    refresh_token = Column(String(300))
    create_time = Column(DateTime)
    update_time = Column(DateTime)
