# schemas.py
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


# ----- Auth -----

class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class UserBase(BaseModel):
    username: str


class UserCreate(UserBase):
    password: str


class UserOut(UserBase):
    id: int
    is_active: bool

    class Config:
        orm_mode = True


# ----- Companies -----

class CompanyBase(BaseModel):
    name: str
    ticker: str
    segment: str


class CompanyCreate(CompanyBase):
    pass


class CompanyOut(CompanyBase):
    id: int

    class Config:
        orm_mode = True


# ----- Dashboard metrics -----

class CompanyMetrics(BaseModel):
    id: int
    name: str
    ticker: str
    segment: str
    price: Optional[float]
    revenue: Optional[float]
    net_income: Optional[float]
    net_margin: Optional[float]
    roe: Optional[float]
    debt_to_equity: Optional[float]
    current_ratio: Optional[float]
    one_year_return: Optional[float]


class DashboardResponse(BaseModel):
    companies: List[CompanyMetrics]


# ----- Company detail -----

class StatementResponse(BaseModel):
    columns: List[str]
    index: List[str]
    data: List[List[Optional[float]]]


class CompanyDetailResponse(BaseModel):
    info: Dict[str, Any]
    ratios: Dict[str, Optional[float]]
    income_statement: Optional[StatementResponse] = None
    balance_sheet: Optional[StatementResponse] = None
    cash_flow: Optional[StatementResponse] = None
