from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import sessionmaker
import os

DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///./app.db')
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith('sqlite') else {})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
metadata = MetaData()

signals = Table(
    'signals', metadata,
    Column('id', Integer, primary_key=True),
    Column('ticker', String),
    Column('side', String),
    Column('entry', Float),
    Column('sl', Float),
    Column('target', Float),
    Column('confidence', Float),
    Column('reason', String),
    Column('created_at', DateTime, server_default=func.now())
)

paper_trades = Table(
    'paper_trades', metadata,
    Column('id', Integer, primary_key=True),
    Column('ticker', String),
    Column('side', String),
    Column('entry', Float),
    Column('exit', Float),
    Column('pnl', Float),
    Column('created_at', DateTime, server_default=func.now())
)

metadata.create_all(engine)
