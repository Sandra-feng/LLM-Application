#!/usr/bin/env python
from sqlalchemy import Column, DateTime, Integer, String
from sqlalchemy.orm import declarative_base

from base_configs.mysql_config import TableConfig

Base = declarative_base()


class RoleMem_Model(Base):
    __tablename__ = TableConfig.ROLE_MEM_TABLE
    id = Column(Integer, primary_key=True, index=True, nullable=False)
    relation_id = Column(String(64), unique=True, index=True, nullable=False)
    role_id = Column(String(64), index=True, nullable=False)
    account_id = Column(String(100))
    status = Column(Integer, default=1, nullable=False)
    create_time = Column(DateTime)
    update_time = Column(DateTime)
