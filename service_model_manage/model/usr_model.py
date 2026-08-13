#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime

Base = declarative_base()

class Usr_Model(Base):
    __tablename__ = TableConfig.USR_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    account_id = Column(String(64), unique=True, index=True,nullable=False)
    account_name = Column(String(64), index=True,nullable=False)
    usr_name = Column(String(64))
    status = Column(Integer,default=1,nullable=False)
    create_time = Column(DateTime)
    update_time = Column(DateTime)
    password = Column(String(100))
    attribute = Column(Integer,default=1)


