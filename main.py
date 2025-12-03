# main.py
from datetime import timedelta
from typing import List
import math
import numpy as np
import pandas as pd
import io
import os
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse,StreamingResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from fastapi.middleware.cors import CORSMiddleware

from auth import (
    get_db,
    get_current_active_user,
    authenticate_user,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    get_password_hash,
)
from database import Base, engine
from finance import (
    fetch_price_history,
    fetch_fundamentals,
    compute_ratios,
    dataframe_to_statement,
)
from models import User, Company
from schemas import (
    UserCreate,
    UserOut,
    Token,
    CompanyCreate,
    CompanyOut,
    DashboardResponse,
    CompanyMetrics,
    CompanyDetailResponse,
    StatementResponse,
)

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Logistics Financial Analytics Web App",
    description="FastAPI + OAuth2 + SQLite + yfinance",
    version="0.1.0",
)

SECRET_KEY_ENV = os.getenv("SECRET_KEY")
if SECRET_KEY_ENV:
    try:
        import auth as _auth_mod
        _auth_mod.SECRET_KEY = SECRET_KEY_ENV
    except Exception:
        pass

# ========= CORS Configuration =========
allowed = os.getenv("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [
    o.strip().rstrip("/") for o in (allowed.split(",") if allowed else [])
    if o and o.strip()
]

allow_all = os.getenv("ALLOW_ALL_CORS", "0") == "1"

if allow_all:
    origins = ["*"]
else:
    origins = ALLOWED_ORIGINS

if allow_all or origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,   # required for Authorization header / cookies when using explicit origins
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # useful log for Render logs
    print("CORS enabled. allow_all:", allow_all, "origins:", origins)
else:
    print("CORS not enabled: no ALLOWED_ORIGINS and ALLOW_ALL_CORS != 1")

PORT = int(os.getenv("PORT", "8000"))


# Serve static front-end
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")



# ========= Helpers =========

def order_statement_rows(df: pd.DataFrame, priorities: list) -> pd.DataFrame:
    """
    Reorder df rows according to an ordered list of priority keywords.
    Each priority matches labels by exact or contains (case-insensitive).
    Unmatched rows are appended in original order.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    orig_index = [str(i) for i in df.index.tolist()]
    used = set()
    ordered_rows = []

    # exact and then contains
    for p in priorities:
        p_low = p.lower()
        # exact match first
        for idx, lab in enumerate(orig_index):
            if idx in used:
                continue
            if lab.lower() == p_low:
                ordered_rows.append(lab)
                used.add(idx)
                break
        # contains match next
        if any(r.lower() == p_low for r in ordered_rows):
            continue
        for idx, lab in enumerate(orig_index):
            if idx in used:
                continue
            if p_low in lab.lower():
                ordered_rows.append(lab)
                used.add(idx)
                break

    # append remaining in original order
    for idx, lab in enumerate(orig_index):
        if idx not in used:
            ordered_rows.append(lab)
            used.add(idx)

    ordered_rows_filtered = [r for r in ordered_rows if r in orig_index]
    if not ordered_rows_filtered:
        return df.copy()
    return df.loc[ordered_rows_filtered]


def _norm_df(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize df: string index/cols, drop fully-empty rows/cols"""
    if df is None or df.empty:
        return pd.DataFrame()
    df2 = df.copy()
    df2.index = df2.index.astype(str)
    df2.columns = [str(c) for c in df2.columns]
    # drop columns/rows that are all NA
    df2 = df2.loc[:, ~df2.isna().all(axis=0)]
    df2 = df2.loc[~df2.isna().all(axis=1)]
    return df2


# Priority lists: tweak these if you need different labels
INCOME_PRIORITIES = [
    "Total Revenue", "Revenue", "Operating Revenue", "Net Revenue",
    "Cost of Revenue", "Cost of Goods Sold", "Gross Profit",
    "Operating Expense", "Selling General and Administrative", "SG&A",
    "Research and Development", "R&D",
    "EBITDA", "EBIT", "Operating Income", "Operating Profit",
    "Income Before Tax", "Income Tax Expense", "Net Income",
    "Net Income Attributable to Parent", "Net Income Common Stockholders",
    "Normalized Income", "Normalized EBITDA", "Diluted EPS", "Basic EPS",
]

BALANCE_PRIORITIES = [
    "Cash", "Cash And Cash Equivalents", "Total Current Assets", "Accounts Receivable",
    "Inventory", "Total Assets",
    "Total Current Liabilities", "Accounts Payable", "Total Liabilities",
    "Long Term Debt", "Total Debt", "Total Stockholder Equity", "Total Equity", "Retained Earnings"
]

CASH_PRIORITIES = [
    "Net Cash Provided By Operating Activities", "Operating Cash Flow",
    "Net Cash Flow From Operating Activities",
    "Capital Expenditures", "Investing Cash Flow",
    "Net Cash Provided By Financing Activities", "Free Cash Flow", "Dividends Paid",
    "Net Change In Cash", "Cash Flow"
]


# ========= AUTH ROUTES =========

@app.post("/register", response_model=UserOut)
def register_user(user_in: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.username == user_in.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_pw = get_password_hash(user_in.password)
    user = User(username=user_in.username, hashed_password=hashed_pw)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@app.post("/token", response_model=Token)
def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    return Token(access_token=access_token, token_type="bearer")


# ========= COMPANY CRUD =========

@app.get("/companies", response_model=List[CompanyOut])
def list_companies(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)
):
    return (
        db.query(Company)
        .filter(Company.owner_id == current_user.id)
        .order_by(Company.segment, Company.name)
        .all()
    )


@app.post("/companies", response_model=CompanyOut, status_code=201)
def create_company(
    company_in: CompanyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    company = Company(
        name=company_in.name,
        ticker=company_in.ticker,
        segment=company_in.segment,
        owner_id=current_user.id,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


@app.delete("/companies/{company_id}", status_code=204)
def delete_company(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    company = (
        db.query(Company)
        .filter(Company.id == company_id, Company.owner_id == current_user.id)
        .first()
    )
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    db.delete(company)
    db.commit()
    return


# ========= DASHBOARD & DETAIL =========

@app.get("/dashboard", response_model=DashboardResponse)
def get_dashboard(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    companies = db.query(Company).filter(Company.owner_id == current_user.id).all()
    if not companies:
        return DashboardResponse(companies=[])

    metrics_list: List[CompanyMetrics] = []

    for c in companies:
        price_hist = fetch_price_history(c.ticker, period="5y")
        fundamentals = fetch_fundamentals(c.ticker)
        ratios = compute_ratios(
            fundamentals["income"],
            fundamentals["balance"],
            fundamentals["cashflow"],
            price_hist,
        )

        metrics_list.append(
            CompanyMetrics(
                id=c.id,
                name=c.name,
                ticker=c.ticker,
                segment=c.segment,
                price=ratios["price"],
                revenue=ratios["revenue"],
                net_income=ratios["net_income"],
                net_margin=ratios["net_margin"],
                roe=ratios["roe"],
                debt_to_equity=ratios["debt_to_equity"],
                current_ratio=ratios["current_ratio"],
                one_year_return=ratios["one_year_return"],
            )
        )

    return DashboardResponse(companies=metrics_list)


@app.get("/companies/{company_id}/detail", response_model=CompanyDetailResponse)
@app.get("/companies/{company_id}/detail", response_model=CompanyDetailResponse)
def company_detail(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # ---------- 1. Fetch company ----------
    c = (
        db.query(Company)
        .filter(Company.id == company_id, Company.owner_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    # ---------- 2. Fetch fundamentals ----------
    fundamentals = fetch_fundamentals(c.ticker)
    income_df = fundamentals.get("income")
    balance_df = fundamentals.get("balance")
    cashflow_df = fundamentals.get("cashflow")
    info_df = fundamentals.get("info")

    # ---------- 3. Price history ----------
    price_hist = fetch_price_history(c.ticker, period="5y")

    # ---------- 4. Compute ratios ----------
    ratios = compute_ratios(
        income=income_df,
        balance=balance_df,
        cashflow=cashflow_df,
        price_hist=price_hist,
    )

    # ---------- 5. Build safe info_dict ----------
    info_dict = {}

    if info_df is not None and not info_df.empty:
        for idx, row in info_df.iterrows():
            val = row["value"]

            # -- Arrays / lists / Series first --
            if isinstance(val, (np.ndarray, pd.Series, list, tuple)):
                arr = np.array(val).flatten()
                if arr.size == 0 or np.all(pd.isna(arr)):
                    continue
                mask = ~pd.isna(arr)
                if not mask.any():
                    continue
                val = arr[mask][0]

            # -- Now scalar --
            if pd.isna(val):
                continue

            # Numeric
            if isinstance(val, (int, float, np.integer, np.floating)):
                try:
                    v = float(val)
                    if math.isnan(v) or math.isinf(v):
                        continue
                    val = v
                except Exception:
                    continue

            # All remaining types (str, bool, etc.) are JSON-safe
            info_dict[idx] = val

    # ---------- 6. Statements (Income, Balance, Cash Flow) ----------
    income_json = dataframe_to_statement(income_df, max_cols=3)
    balance_json = dataframe_to_statement(balance_df, max_cols=3)
    cf_json = dataframe_to_statement(cashflow_df, max_cols=3)

    def to_statement(obj):
        if obj is None:
            return None
        return StatementResponse(
            columns=obj["columns"],
            index=obj["index"],
            data=obj["data"],
        )

    # ---------- 7. Final JSON-safe response ----------
    return CompanyDetailResponse(
        info=info_dict,
        ratios=ratios,
        income_statement=to_statement(income_json),
        balance_sheet=to_statement(balance_json),
        cash_flow=to_statement(cf_json),
    )



@app.get("/companies/{company_id}/download", response_class=StreamingResponse)
def download_company_excel(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
):
    # validate company
    c = (
        db.query(Company)
        .filter(Company.id == company_id, Company.owner_id == current_user.id)
        .first()
    )
    if not c:
        raise HTTPException(status_code=404, detail="Company not found")

    # fetch fundamentals
    fundamentals = fetch_fundamentals(c.ticker)
    income_df = fundamentals.get("income")
    balance_df = fundamentals.get("balance")
    cashflow_df = fundamentals.get("cashflow")
    info_df = fundamentals.get("info")

    # normalize and order
    income_df_norm = _norm_df(income_df)
    balance_df_norm = _norm_df(balance_df)
    cashflow_df_norm = _norm_df(cashflow_df)

    ordered_income = order_statement_rows(income_df_norm, INCOME_PRIORITIES) if not income_df_norm.empty else pd.DataFrame()
    ordered_balance = order_statement_rows(balance_df_norm, BALANCE_PRIORITIES) if not balance_df_norm.empty else pd.DataFrame()
    ordered_cash = order_statement_rows(cashflow_df_norm, CASH_PRIORITIES) if not cashflow_df_norm.empty else pd.DataFrame()

    # build excel
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        workbook = writer.book
        header_format = workbook.add_format({"bold": True, "bg_color": "#F3F6F9", "border": 1})
        num_format = workbook.add_format({"num_format": "#,##0.00", "border": 1})
        int_format = workbook.add_format({"num_format": "#,##0", "border": 1})
        text_format = workbook.add_format({"border": 1})

        def write_sheet(name: str, df: pd.DataFrame):
            if df is None or df.empty:
                pd.DataFrame({"Note": [f"No data available for {name}"]}).to_excel(writer, sheet_name=name, index=False)
                ws = writer.sheets[name]
                ws.set_column(0, 0, 60, text_format)
                return
            df_to_write = df.copy()
            df_to_write.insert(0, "__line__", df_to_write.index)
            df_to_write.to_excel(writer, sheet_name=name, index=False)
            ws = writer.sheets[name]
            nrows, ncols = df_to_write.shape
            for col_idx, col_name in enumerate(df_to_write.columns):
                ws.write(0, col_idx, col_name, header_format)
                if col_idx == 0:
                    ws.set_column(col_idx, col_idx, 36, text_format)
                else:
                    series = df_to_write.iloc[:, col_idx]
                    if pd.api.types.is_numeric_dtype(series) or series.apply(lambda v: isinstance(v, (int, float, np.integer, np.floating))).any():
                        # choose integer vs float
                        any_float = any(isinstance(v, float) and (abs(v - int(v)) > 1e-8) for v in series.dropna().tolist()[:50])
                        ws.set_column(col_idx, col_idx, 18, num_format if any_float else int_format)
                    else:
                        ws.set_column(col_idx, col_idx, 24, text_format)
            try:
                ws.autofilter(0, 0, nrows, ncols - 1)
            except Exception:
                pass

        write_sheet("Income Statement", ordered_income)
        write_sheet("Balance Sheet", ordered_balance)
        write_sheet("Cash Flow", ordered_cash)

        # Company Info sheet (best-effort)
        try:
            if info_df is not None and not info_df.empty:
                if (info_df.shape[1] == 1) and (info_df.columns[0] == "value"):
                    info_pairs = [(str(k), v) for k, v in info_df["value"].to_dict().items()]
                    info_flat = pd.DataFrame(info_pairs, columns=["Key", "Value"])
                else:
                    pairs = []
                    if isinstance(info_df, pd.DataFrame):
                        for idx, row in info_df.iterrows():
                            if hasattr(row, "tolist"):
                                pairs.append((str(idx), ", ".join([str(x) for x in row.tolist()])))
                            else:
                                pairs.append((str(idx), str(row)))
                    info_flat = pd.DataFrame(pairs, columns=["Key", "Value"])
                if not info_flat.empty:
                    info_flat.to_excel(writer, sheet_name="Company Info", index=False)
                    w = writer.sheets["Company Info"]
                    w.set_column(0, 0, 30, text_format)
                    w.set_column(1, 1, 50, text_format)
        except Exception:
            pass

    output.seek(0)
    filename = f"{c.name.replace(' ', '_')}_financials.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )