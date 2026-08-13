#!/usr/bin/env python
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

from base_configs.mysql_config import TableConfig

Base = declarative_base()


class Usr_Model(Base):
    __tablename__ = TableConfig.USR_TABLE
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    account_id = Column(String(64), unique=True, index=True, nullable=False)
    account_name = Column(String(64), index=True, nullable=False)
    usr_name = Column(String(64))
    status = Column(Integer, default=1, nullable=False)
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    password = Column(String(100))
    attribute = Column(Integer, default=1)
