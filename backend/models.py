from datetime import datetime
from sqlalchemy import Column, Integer, String, DateTime, Float, Text

from .database import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    creator = Column(String(200), nullable=False)
    category = Column(String(50), nullable=False)
    goal_microalgos = Column(Integer, nullable=False)
    token_asset_id = Column(Integer, nullable=False)
    token_rate_per_algo = Column(Float, nullable=False)  # tokens per ALGO
    token_pool = Column(Integer, nullable=False)

    description = Column(Text, default="")
    problem = Column(Text, default="")
    solution = Column(Text, default="")
    business_model = Column(Text, default="")
    investment_ask = Column(Text, default="")
    incentive_pool = Column(Text, default="")
    contact_email = Column(String(200), default="")
    project_link = Column(String(500), default="")

    created_at = Column(DateTime, default=datetime.utcnow)
    deadline_at = Column(DateTime, nullable=False)

    # Chain deployment
    app_id = Column(Integer, nullable=True)
    escrow_address = Column(String(100), nullable=True)
