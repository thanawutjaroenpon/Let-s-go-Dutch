from fastapi import FastAPI, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, DateTime, func, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from pyzbar.pyzbar import decode
from PIL import Image
import io
import re
import time
import httpx
from datetime import datetime

# 🔌 Database config
DATABASE_URL = "postgresql://postgres:p%40assw0rd@localhost:5433/dutch"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# 🌐 FastAPI app setup
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 📦 Database models
class SlipHistory(Base):
    __tablename__ = 'slip_history'
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    amount = Column(Numeric)
    promptpay = Column(String)
    status = Column(Boolean)
    created_at = Column(DateTime, server_default=func.now())

class SharedState(Base):
    __tablename__ = 'shared_state'
    id = Column(Integer, primary_key=True)
    data = Column(JSONB)

Base.metadata.create_all(bind=engine)

# 🧠 Helper: decode QR code
def decode_qr_from_image(img_data):
    image = Image.open(io.BytesIO(img_data)).convert('RGB')
    decoded = decode(image)
    for d in decoded:
        data = d.data.decode()
        if "000201" in data and "5303" in data:
            return data
    return None

# 🧠 Helper: extract PromptPay phone & amount
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

# 🧠 Helper: extract text using iApp OCR API
async def extract_text_from_image_api(file: UploadFile):
    api_url = "https://api.iapp.co.th/ocr/v3/receipt/file"
    headers = {"apikey": "demo"}
    
    async with httpx.AsyncClient() as client:
        files = {
            "file": (file.filename, await file.read(), "image/jpeg"),
            "return_image": (None, "false")
        }
        response = await client.post(api_url, headers=headers, files=files)
        return response.json()

def parse_kbank_slip_text(ocr_data: dict):
    """Parse KBank slip text from iApp OCR response"""
    result = {
        "invoiceType": "สลิปโอนเงิน",
        "invoiceBook": None,
        "invoiceID": None,
        "invoiceDate": None,
        "purchaseOrderID": None,
        "issuerName": None,
        "issuerAddress": None,
        "issuerTaxID": None,
        "issuerPhone": None,
        "customerName": None,
        "customerAddress": None,
        "customerTaxID": None,
        "customerPhone": None,
        "items": [],
        "totalCost": None,
        "discount": 0,
        "totalCostAfterDiscount": None,
        "vat": 0,
        "grandTotal": None
    }

    # Extract from iApp OCR response
    if 'processed' in ocr_data:
        processed = ocr_data['processed']
        
        # Map fields from iApp response to our structure
        result['invoiceID'] = processed.get('invoiceID')
        result['invoiceDate'] = processed.get('invoiceDate')
        result['issuerName'] = processed.get('issuerName')
        result['customerName'] = processed.get('customerName')
        result['issuerTaxID'] = processed.get('issuerTaxID')
        result['customerTaxID'] = processed.get('customerTaxID')
        
        # Handle amount fields
        if 'grandTotal' in processed:
            amount = float(processed['grandTotal'])
            result['grandTotal'] = amount
            result['totalCost'] = amount
            result['totalCostAfterDiscount'] = amount

    return result

# 📤 API: Upload slip images (QR decode + OCR)
@app.post("/api/slip/upload")
async def upload_slips(files: list[UploadFile] = File(...)):
    session = SessionLocal()
    results = []

    for file in files:
        start_time = time.time()
        content = await file.read()
        
        # QR code processing
        qr_data = decode_qr_from_image(content)
        phone, amount = extract_promptpay_info(qr_data) if qr_data else (None, None)
        is_valid = phone is not None and amount is not None
        
        # Reset file pointer after reading for QR code
        await file.seek(0)
        
        # OCR processing via API
        ocr_data = await extract_text_from_image_api(file)
        processed_data = parse_kbank_slip_text(ocr_data)
        
        # If we found amount from QR but not from OCR, use QR amount
        if amount is not None and processed_data.get("grandTotal") is None:
            processed_data["grandTotal"] = amount
            processed_data["totalCost"] = amount
            processed_data["totalCostAfterDiscount"] = amount

        # Save to DB
        slip = SlipHistory(
            filename=file.filename,
            amount=amount if amount else processed_data.get("grandTotal"),
            promptpay=phone,
            status=is_valid
        )
        session.add(slip)
        session.commit()

        process_time = int((time.time() - start_time) * 1000)
        
        results.append({
            "message": "success",
            "raw": {
                "qr_data": qr_data,
                "ocr_data": ocr_data
            },
            "processed": processed_data,
            "template": "receipt",
            "iapp": {
                "page": 1,
                "char": len(str(ocr_data))  # Approximate character count
            },
            "process_ms": process_time
        })

    return {"results": results}

# 📥 API: Get recent slips
@app.get("/api/slip/history")
def get_slip_history():
    session = SessionLocal()
    slips = session.query(SlipHistory).order_by(SlipHistory.created_at.desc()).limit(20).all()
    return [{
        "filename": s.filename,
        "amount": float(s.amount) if s.amount else None,
        "promptpay": s.promptpay,
        "status": s.status,
        "created_at": s.created_at.isoformat()
    } for s in slips]

# 🧠 API: Save shared state
@app.post("/api/state/save")
async def save_state(request: Request):
    session = SessionLocal()
    payload = await request.json()

    session.query(SharedState).delete()
    session.commit()

    state = SharedState(data=payload)
    session.add(state)
    session.commit()
    return {"status": "ok"}

# 📤 API: Load shared state
@app.get("/api/state/load")
def load_state():
    session = SessionLocal()
    latest = session.query(SharedState).order_by(SharedState.id.desc()).first()
    return latest.data if latest else {}