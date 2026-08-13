#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from sqlalchemy.orm import declarative_base
from base_configs.mysql_config import TableConfig
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String ,DateTime

Base = declarative_base()

class Resource_Model(Base):
    __tablename__ = TableConfig.RES_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    res_id = Column(String(64), unique=True, index=True,nullable=False)
    res_name = Column(String(64), index=True,nullable=False)
    res_description = Column(String(100))
    status = Column(Integer,default=1,nullable=False)
    create_time = Column(DateTime)
    update_time = Column(DateTime)

