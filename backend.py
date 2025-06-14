from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, DateTime, func, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
from PIL import Image
import io
import time
import httpx
from datetime import datetime
from typing import Optional, Dict, Any

# Database config
DATABASE_URL = "postgresql://postgres:p%40assw0rd@localhost:5433/dutch"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# Database models
class SlipHistory(Base):
    __tablename__ = 'slip_history'
    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String)
    amount = Column(Numeric)
    status = Column(Boolean)
    verified = Column(Boolean, default=False)
    issuer_name = Column(String)
    receiver_name = Column(String)
    created_at = Column(DateTime, server_default=func.now())

class SharedState(Base):
    __tablename__ = 'shared_state'
    id = Column(Integer, primary_key=True)
    data = Column(JSONB)

# Create all tables (won't recreate if they exist)
Base.metadata.create_all(bind=engine)

# FastAPI app setup
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

async def extract_text_from_image_api(file: UploadFile):
    api_url = "https://api.iapp.co.th/ocr/v3/receipt/file"
    headers = {"apikey": "GZY8mo87ZiEqeqZklCOrNjOgAnqBfO1T"}
    
    try:
        async with httpx.AsyncClient() as client:
            files = {
                "file": (file.filename, await file.read(), "image/jpeg"),
                "return_image": (None, "false")
            }
            response = await client.post(api_url, headers=headers, files=files)
            return response.json()
    except Exception as e:
        print(f"Error calling OCR API: {e}")
        return {}

def parse_kbank_slip_text(ocr_data: dict):
    result = {
        "invoiceType": "สลิปโอนเงิน",
        "issuerName": None,
        "customerName": None,
        "grandTotal": None
    }

    if 'processed' in ocr_data:
        processed = ocr_data['processed']
        result['issuerName'] = processed.get('issuerName')
        result['customerName'] = processed.get('customerName')
        
        if 'grandTotal' in processed:
            try:
                amount = float(processed['grandTotal'])
                result['grandTotal'] = amount
            except (ValueError, TypeError):
                result['grandTotal'] = None

    return result

def verify_slip_payment(issuer_name: str, receiver_name: str, amount: float, session) -> bool:
    if not issuer_name or not receiver_name or not amount:
        return False

    state = session.query(SharedState).order_by(SharedState.id.desc()).first()
    if not state or not state.data:
        return False

    payers = state.data.get('payers', [])
    payer_names = [payer['name'] for payer in payers]
    
    # Check if both names exist in payers
    if issuer_name not in payer_names or receiver_name not in payer_names:
        return False

    # Calculate net balances
    net_balances = {payer['name']: 0 for payer in payers}

    for item in state.data.get('items', []):
        split_names = [name for name, checked in item['splitWith'].items() if checked]
        if split_names:
            share = item['price'] / len(split_names)
            for name in split_names:
                net_balances[name] += share
        
        if item['paidBy']:
            net_balances[item['paidBy']] -= item['price']

    # Check if payment matches expected transfer
    expected_amount = abs(net_balances.get(receiver_name, 0))
    return abs(expected_amount - amount) < 0.01

# API endpoints
@app.post("/api/slip/upload")
async def upload_slips(files: list[UploadFile] = File(...)):
    session = SessionLocal()
    results = []

    for file in files:
        try:
            start_time = time.time()
            
            # OCR processing only (no QR code)
            ocr_data = await extract_text_from_image_api(file)
            processed_data = parse_kbank_slip_text(ocr_data)
            
            # Get details from OCR
            amount = processed_data.get("grandTotal")
            issuer_name = processed_data.get("issuerName")
            receiver_name = processed_data.get("customerName")
            
            # Validate slip
            is_valid = amount is not None
            is_verified = False
            
            if amount is not None and issuer_name and receiver_name:
                is_verified = verify_slip_payment(
                    issuer_name=issuer_name,
                    receiver_name=receiver_name,
                    amount=amount,
                    session=session
                )

            # Save to database
            slip = SlipHistory(
                filename=file.filename,
                amount=amount,
                status=is_valid,
                verified=is_verified,
                issuer_name=issuer_name,
                receiver_name=receiver_name
            )
            session.add(slip)
            session.commit()

            process_time = int((time.time() - start_time) * 1000)
            
            results.append({
                "filename": file.filename,
                "valid": is_valid,
                "verified": is_verified,
                "amount": amount,
                "issuer_name": issuer_name,
                "receiver_name": receiver_name,
                "process_ms": process_time
            })

        except Exception as e:
            print(f"Error processing file {file.filename}: {e}")
            session.rollback()
            results.append({
                "filename": file.filename,
                "error": str(e),
                "valid": False,
                "verified": False
            })
        finally:
            await file.close()

    return {"results": results}

@app.get("/api/slip/history")
def get_slip_history():
    session = SessionLocal()
    slips = session.query(SlipHistory).order_by(SlipHistory.created_at.desc()).limit(20).all()
    return [{
        "filename": s.filename,
        "amount": float(s.amount) if s.amount else None,
        "status": s.status,
        "verified": s.verified,
        "issuer_name": s.issuer_name,
        "receiver_name": s.receiver_name,
        "created_at": s.created_at.isoformat()
    } for s in slips]

@app.post("/api/state/save")
async def save_state(request: Request):
    session = SessionLocal()
    try:
        payload = await request.json()
        
        # Clear existing state
        session.query(SharedState).delete()
        
        # Save new state
        state = SharedState(data=payload)
        session.add(state)
        session.commit()
        return {"status": "ok"}
    except Exception as e:
        session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        session.close()

@app.get("/api/state/load")
def load_state():
    session = SessionLocal()
    try:
        latest = session.query(SharedState).order_by(SharedState.id.desc()).first()
        return latest.data if latest else {}
    finally:
        session.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)