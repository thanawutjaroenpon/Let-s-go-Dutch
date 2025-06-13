from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pyzbar.pyzbar import decode
from PIL import Image
import io
from fastapi import Request
from sqlalchemy import Text
from sqlalchemy.dialects.postgresql import JSONB

DATABASE_URL = "postgresql://postgres:p%40assw0rd@localhost:5433/dutch"


engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# DB model
class SlipHistory(Base):
    __tablename__ = 'slip_history'
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    amount = Column(Numeric)
    promptpay = Column(String)
    status = Column(Boolean)
    created_at = Column(DateTime, server_default=func.now())

Base.metadata.create_all(bind=engine)

class SharedState(Base):
    __tablename__ = 'shared_state'
    id = Column(Integer, primary_key=True)
    data = Column(JSONB)

Base.metadata.create_all(bind=engine)

# QR decode helper
def decode_qr_from_image(img_data):
    image = Image.open(io.BytesIO(img_data)).convert('RGB')
    decoded = decode(image)
    for d in decoded:
        data = d.data.decode()
        if "000201" in data and "5303" in data:
            return data
    return None

# Extract amount & phone from PromptPay QR raw string (simplified)
def extract_promptpay_info(qr_string: str):
    try:
        phone = None
        amount = None
        if "0113" in qr_string:
            idx = qr_string.find("0113") + 4
            phone = qr_string[idx:idx+13]
        if "54" in qr_string:
            idx = qr_string.find("54") + 2
            length = int(qr_string[idx:idx+2])
            amount = qr_string[idx+2:idx+2+length]
        return phone, float(amount) if amount else None
    except:
        return None, None

# Upload API
@app.post("/api/slip/upload")
async def upload_slips(files: list[UploadFile] = File(...)):
    session = SessionLocal()
    results = []

    for file in files:
        content = await file.read()
        qr_data = decode_qr_from_image(content)
        phone, amount = extract_promptpay_info(qr_data) if qr_data else (None, None)
        is_valid = phone is not None and amount is not None

        # Save to DB
        slip = SlipHistory(
            filename=file.filename,
            amount=amount,
            promptpay=phone,
            status=is_valid
        )
        session.add(slip)
        session.commit()

        results.append({
            "filename": file.filename,
            "valid": is_valid,
            "amount": amount,
            "promptpay": phone
        })

    return { "results": results }
@app.get("/api/slip/history")
def get_slip_history():
    session = SessionLocal()
    slips = session.query(SlipHistory).order_by(SlipHistory.created_at.desc()).limit(20).all()
    return [ {
        "filename": s.filename,
        "amount": float(s.amount) if s.amount else None,
        "promptpay": s.promptpay,
        "status": s.status,
        "created_at": s.created_at.isoformat()
    } for s in slips ]

@app.post("/api/state/save")
async def save_state(request: Request):
    session = SessionLocal()
    payload = await request.json()

    # ล้างข้อมูลเก่า (กรณีมีหลาย record)
    session.query(SharedState).delete()
    session.commit()

    state = SharedState(data=payload)
    session.add(state)
    session.commit()
    return {"status": "ok"}

# Endpoint สำหรับโหลด shared state
@app.get("/api/state/load")
def load_state():
    session = SessionLocal()
    latest = session.query(SharedState).order_by(SharedState.id.desc()).first()
    return latest.data if latest else {}
