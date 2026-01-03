
import pdfplumber
import pandas as pd
import re
from datetime import datetime
import google.genai as genai
import os
import json
from dotenv import load_dotenv

load_dotenv()

def normalize_date(date_str):
    """
    Parses date strings like '02/02/2026' or '06 November 2025'
    Returns 'YYYY-MM-DD' for HTML input type='date'
    """
    date_str = date_str.strip()
    # Try DD/MM/YYYY
    try:
        dt = datetime.strptime(date_str, "%d/%m/%Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
        
    # Try DD Month YYYY
    try:
        dt = datetime.strptime(date_str, "%d %B %Y")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    
    # Return original if parsing fails (fallback)
    return date_str

def normalize_time_range(time_str):
    """
    Parses time strings like '10.15 a.m. to 11.00 a.m.'
    Returns tuple ('HH:MM', 'HH:MM') for start and end times (24-hour).
    Returns (None, None) if parsing fails.
    """
    time_str = time_str.strip().lower()
    time_str = time_str.replace("a.m.", "am").replace("p.m.", "pm")
    time_str = time_str.replace("noon", "12:00 pm")
    
    # Regex to capture all time occurrences
    # Matches: 10.15, 10:15, 1, 12, optionally am/pm
    pattern = r'(\d{1,2})[.:]?(\d{2})?\s?(am|pm)?'
    matches = list(re.finditer(pattern, time_str))
    
    if len(matches) < 2:
        # Maybe just one time found? Try to fallback or return single
        if len(matches) == 1:
            return convert_match_to_24h(matches[0], time_str), ""
        return "", ""
        
    start_match = matches[0]
    end_match = matches[1]
    
    start_time = convert_match_to_24h(start_match, time_str, is_end=False)
    end_time = convert_match_to_24h(end_match, time_str[start_match.end():], is_end=True)
    
    return start_time, end_time

def convert_match_to_24h(match, context_str, is_end=False):
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    meridiem = match.group(3)
    
    # Heuristic for missing meridiem
    if not meridiem:
        # If it's the start time and there's a later 'pm', assume 'am' if hour < 12?
        # Or look ahead in context
        if "pm" in context_str and "am" not in context_str[:10]: 
            # If context has pm and we are looking at something before it, it might be am/pm?
            # It's tricky. 
            pass
            
    # Simple logic: if < 7, likely PM (exams don't start at 1 AM). if >= 7 and < 12, likely AM.
    # 12 is PM usually unless 12 am (midnight).
    
    # Better: Use the raw string check
    if not meridiem:
        if "pm" in context_str: meridiem = "pm"
        elif "am" in context_str: meridiem = "am"
    
    if not meridiem:
        # Fallback Logic
        if hour < 7: meridiem = 'pm'
        else: meridiem = 'am'

    if meridiem == 'pm' and hour != 12:
        hour += 12
    if meridiem == 'am' and hour == 12:
        hour = 0
        
    return f"{hour:02d}:{minute:02d}"

def extract_sessions_from_pdf(pdf_path):
    """
    Extracts session data from the PDF.
    """
    sessions = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # ... (Existing table extraction logic same as before, just calling new function)
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                # --- STRATEGY 1: Detect Header (Smart Mode) ---
                header_row = None
                header_idx = -1
                
                for idx, row in enumerate(table[:5]):
                    row_texts = [str(c).upper().strip() if c else "" for c in row]
                    if "DATE" in row_texts and "TIME" in row_texts:
                        header_row = row_texts
                        header_idx = idx
                        break
                
                if header_row:
                    try:
                        date_col_idx = header_row.index("DATE")
                        time_col_idx = header_row.index("TIME")
                        
                        subject_cols = []
                        for c_idx, col_name in enumerate(header_row):
                            if c_idx not in [date_col_idx, time_col_idx] and col_name and "DAY" not in col_name:
                                subject_cols.append((c_idx, col_name))
                        
                        current_date = None
                        
                        for row_idx in range(header_idx + 1, len(table)):
                            row = table[row_idx]
                            row = [str(cell).strip() if cell else "" for cell in row]
                            
                            if len(row) <= max(date_col_idx, time_col_idx): continue
                            
                            date_val = row[date_col_idx]
                            time_val = row[time_col_idx]
                            
                            if "MSE" in date_val.upper() or "EXAM" in date_val.upper(): continue

                            if any(c.isdigit() for c in date_val):
                                current_date = date_val
                            
                            d_to_use = date_val if date_val else current_date
                            
                            if not d_to_use or not time_val or len(time_val) < 4: continue
                                
                            # Convert Time
                            start_t, end_t = normalize_time_range(time_val)
                                
                            for (subj_idx, stream_name) in subject_cols:
                                if subj_idx < len(row):
                                    subj_text = row[subj_idx]
                                    if len(subj_text) > 2 and "---" not in subj_text:
                                        subj_clean = subj_text.replace('\n', ' ')
                                        subj_clean = subj_text.replace('\n', ' ')
                                        
                                        sessions.append({
                                            "date": normalize_date(d_to_use),
                                            "start_time": start_t,
                                            "end_time": end_t,
                                            "subject": subj_clean,
                                            "department": stream_name
                                        })
                    except ValueError:
                        pass
                        
                else:
                    # --- STRATEGY 2: Legacy Fallback ---
                    for row in table:
                        row = [str(cell).strip() if cell else "" for cell in row]
                        if len(row) < 3: continue
                        
                        date_val = row[0]
                        time_val = row[1]
                        subj_val = row[-1]
                        
                        if len(date_val) > 4 and any(c.isdigit() for c in date_val) and "Date" not in date_val:
                             if len(subj_val) > 2:
                                 if "Subject" in subj_val or "Paper" in subj_val: continue
                                 
                                 start_t, end_t = normalize_time_range(time_val)
                                 
                                 sessions.append({
                                    "date": normalize_date(date_val),
                                    "start_time": start_t,
                                    "end_time": end_t,
                                    "subject": subj_val,
                                    "department": ""
                                })
    return sessions

def extract_to_excel(pdf_path, excel_path):
    all_data = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            print(f"Processing page {i+1}...")
            tables = page.extract_tables()
            
            for table in tables:
                # table is a list of lists
                for row in table:
                    # Clean None values
                    cleaned_row = [cell.strip() if cell else "" for cell in row]
                    all_data.append(cleaned_row)

    if all_data:
        df = pd.DataFrame(all_data)



def parse_schedule_with_gemini(pdf_path):
    """
    Parses the schedule PDF using Gemini API via google-genai SDK.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env")
        return []

    try:
        from google import genai
        from google.genai import types
        
        client = genai.Client(api_key=api_key)
        
        # Upload the file using new SDK
        # The argument might be 'file' or positional. Let's try 'file'.
        file_upload = client.files.upload(file=pdf_path)
        
        prompt = """
        You are an expert data extraction assistant extracting data from an exam schedule PDF.
        
        Extract all exam sessions from the document into a JSON list.
        Each item in the list must have the following fields:
        - "date": Date of the exam in YYYY-MM-DD format.
        - "start_time": Start time in HH:MM (24-hour) format.
        - "end_time": End time in HH:MM (24-hour) format.
        - "subject": The full name of the subject/paper.
        - "department": The department or stream (e.g., CSE, MECH, MBA) if clearly identifiable, else empty string.
        
        Rules:
        1. Ignore header rows or irrelevant text.
        2. Ensure dates are normalized.
        3. Convert all times to 24-hour format.
        4. If a session spans multiple subjects/departments listed in columns, create separate entries for each.
        5. RETURN ONLY RAW JSON. NO MARKDOWN FORMATTING.
        """
        
        # New model name request
        model_name = "gemini-2.5-flash" 
        
        # Retry logic for handling 503 errors
        import time
        max_retries = 3
        retry_delay = 2  # seconds

        for attempt in range(max_retries):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=[file_upload, prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json"
                    )
                )
                break # Success, exit loop
            except Exception as e:
                # Check for 503 or overload in error message
                error_str = str(e)
                if attempt < max_retries - 1 and ("503" in error_str or "overloaded" in error_str.lower()):
                    print(f"Gemini overloaded (Attempt {attempt+1}/{max_retries}). Retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise e # Re-raise if out of retries or unknown error

        try:
            raw_data = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
             # Clean up
             text = response.text if response.text else ""
             text = text.replace('```json', '').replace('```', '').strip()
             raw_data = json.loads(text)
        
        # Map department names to short codes
        # Order matters! Check more specific patterns first
        dept_mapping = [
            ('electronics and computer', 'EXCS'),
            ('electronics & computer', 'EXCS'),
            ('computer engineering', 'CMPN'),
            ('computer', 'CMPN'),
            ('information technology', 'INFT'),
            ('information', 'INFT'),
            ('electronics & telecommunication', 'EXTC'),
            ('electronics and telecommunication', 'EXTC'),
            ('telecommunication', 'EXTC'),
            ('biomedical', 'BIOM'),
            ('cmpn', 'CMPN'),
            ('inft', 'INFT'),
            ('excs', 'EXCS'),
            ('extc', 'EXTC'),
            ('biom', 'BIOM')
        ]
        
        # Process and shorten department names
        for session in raw_data:
            if 'department' in session and session['department']:
                dept_lower = session['department'].lower().strip()
                # Try exact match or partial match in order
                for pattern, short_code in dept_mapping:
                    if pattern in dept_lower:
                        session['department'] = short_code
                        break
        
        return raw_data
        
    except Exception as e:
        print(f"Error parsing with Gemini: {e}")
        return []