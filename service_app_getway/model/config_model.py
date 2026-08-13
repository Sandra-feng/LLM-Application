#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from sqlalchemy.orm import declarative_base
from service_app_getway.base_configs.mysql_config import TableConfig
from sqlalchemy import JSON, Column, ForeignKey, Integer, String ,DateTime

Base = declarative_base()

class Config_Model(Base):
    __tablename__ = TableConfig.CONFIG_TABLE
    id = Column(Integer, primary_key=True, index=True,nullable=False)
    config_id = Column(String(64), unique=True, index=True,nullable=False)
    config_name = Column(String(64), index=True,nullable=False)
    config_description = Column(JSON)
    status = Column(Integer,default=1,nullable=False)
    create_time = Column(DateTime)
    update_time = Column(DateTime)

