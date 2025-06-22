import uvicorn
from fastapi import FastAPI, UploadFile, File, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import create_engine, Column, Integer, String, Numeric, Boolean, DateTime, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import JSONB
import time
from datetime import datetime
from typing import Optional

# --- OCR Imports ---
import easyocr
import cv2
import re
import numpy as np
import io

# --- OCR Model Initialization (Load once on startup) ---
print("Initializing EasyOCR Reader... This may take a moment.")
# Initialize the reader. Set gpu=False if you are not using a GPU.
reader = easyocr.Reader(['th', 'en'], gpu=False)
print("EasyOCR Reader initialized.")

# --- Database Configuration ---
DATABASE_URL = "postgresql://postgres:p%40assw0rd@localhost:5433/dutch"
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()

# --- Database Models ---
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

# Create all database tables if they don't exist
Base.metadata.create_all(bind=engine)

# --- FastAPI App Setup ---
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Local OCR Logic (from input_file_0.py, adapted for FastAPI) ---

def extract_value_from_text(text, keyword):
    """
    Checks if a keyword is in the text and extracts the value that follows it,
    all within the same string.
    """
    if keyword in text:
        parts = text.split(keyword)
        if len(parts) > 1:
            value = parts[1].strip()
            value = re.sub(r'^\s*[:\s-]\s*', '', value)
            if value:
                return value
    return None

def find_info_on_slip(image: np.ndarray):
    """
    Performs OCR on a bank slip image (as a numpy array) and extracts information.
    The easyocr.Reader (`reader`) is passed in to reuse the loaded model.
    """
    print("Reading text from the image using EasyOCR...")
    results = reader.readtext(image, paragraph=False, detail=1)

    sender_name, receiver_name, total_amount = None, None, None
    keyword_map = [
        (("จาก",), 'sender'),
        (("ไปยัง", "ถึง"), 'receiver'),
        (("จำนวนเงิน", "ยอดชำระ", "ยอดรวม"), 'amount')
    ]

    # Primary Strategy: Find keyword and then find the value
    for i, (bbox, text, prob) in enumerate(results):
        cleaned_text = text.strip()
        for keywords, info_type in keyword_map:
            for keyword in keywords:
                if keyword in cleaned_text:
                    value = None
                    extracted_value = extract_value_from_text(cleaned_text, keyword)
                    if extracted_value:
                        value = extracted_value
                    elif i + 1 < len(results):
                        value = results[i + 1][1].strip()
                        
                    if value:
                        if info_type == 'sender' and not sender_name:
                            sender_name = value
                        elif info_type == 'receiver' and not receiver_name:
                            receiver_name = value
                        elif info_type == 'amount' and not total_amount:
                            amount_match = re.search(r'[\d,.]+', value)
                            if amount_match:
                                try:
                                    cleaned_amount = amount_match.group(0).replace(',', '')
                                    total_amount = float(cleaned_amount)
                                except (ValueError, IndexError):
                                    pass

    # Fallback Strategy: Use prefixes if names are missing
    if not sender_name or not receiver_name:
        personal_prefixes = ['นาย', 'นาง', 'น.ส.', 'นางสาว', 'บจก.', 'หจก.']
        found_names = []
        for (bbox, text, prob) in results:
            for prefix in personal_prefixes:
                if text.strip().startswith(prefix):
                    found_names.append(text.strip())
                    break
        
        if not sender_name and len(found_names) > 0:
            sender_name = found_names[0]
        if not receiver_name and len(found_names) > 1 and found_names[1] != sender_name:
            receiver_name = found_names[1]

    return sender_name, receiver_name, total_amount


async def extract_text_from_image_api(file: UploadFile):
    """
    Replaces the external API call with the local EasyOCR system.
    """
    try:
        # Read image from upload file into memory
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if image is None:
            print(f"Error: Could not decode image {file.filename}.")
            return {}

        # Process the image with our local OCR function
        sender, receiver, amount = find_info_on_slip(image)

        # Return data in the format expected by the next function
        return {
            "processed": {
                "issuerName": sender,
                "customerName": receiver,
                "grandTotal": amount
            }
        }
    except Exception as e:
        print(f"Error in local OCR processing: {e}")
        return {}


# --- Existing Application Logic (from input_file_1.py) ---

def parse_kbank_slip_text(ocr_data: dict):
    """
    Parses the output from our OCR function.
    """
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
        
        if 'grandTotal' in processed and processed['grandTotal'] is not None:
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
    
    if issuer_name not in payer_names or receiver_name not in payer_names:
        return False

    net_balances = {payer['name']: 0 for payer in payers}
    for item in state.data.get('items', []):
        split_names = [name for name, checked in item['splitWith'].items() if checked]
        if split_names:
            share = item['price'] / len(split_names)
            for name in split_names:
                net_balances[name] += share
        
        if item['paidBy']:
            net_balances[item['paidBy']] -= item['price']

    expected_amount = abs(net_balances.get(receiver_name, 0))
    return abs(expected_amount - amount) < 0.01

# --- API Endpoints ---

@app.post("/api/slip/upload")
async def upload_slips(files: list[UploadFile] = File(...)):
    session = SessionLocal()
    results = []

    for file in files:
        try:
            start_time = time.time()
            
            ocr_data = await extract_text_from_image_api(file)
            processed_data = parse_kbank_slip_text(ocr_data)
            
            amount = processed_data.get("grandTotal")
            issuer_name = processed_data.get("issuerName")
            receiver_name = processed_data.get("customerName")
            
            is_valid = amount is not None
            is_verified = False
            
            if is_valid and issuer_name and receiver_name:
                is_verified = verify_slip_payment(
                    issuer_name=issuer_name,
                    receiver_name=receiver_name,
                    amount=amount,
                    session=session
                )

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
    
    session.close()
    return {"results": results}

@app.get("/api/slip/history")
def get_slip_history():
    session = SessionLocal()
    try:
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
    finally:
        session.close()

@app.post("/api/state/save")
async def save_state(request: Request):
    session = SessionLocal()
    try:
        payload = await request.json()
        session.query(SharedState).delete()
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
    uvicorn.run(app, host="0.0.0.0", port=8000)