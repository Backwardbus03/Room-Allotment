import pdfplumber
import pandas as pd

def extract_sessions_from_pdf(pdf_path):
    """
    Extracts session data from the PDF.
    Supports:
    1. Legacy Format: Col 0=Date, Col 1=Time, Col 5=Subject
    2. Multi-Stream Format: Header with DATE, TIME, and Stream Codes (INFT, CMPN, etc.)
    """
    sessions = []
    
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table: continue
                
                # --- STRATEGY 1: Detect Header (Smart Mode) ---
                header_row = None
                header_idx = -1
                
                # Scan first 5 rows for header
                for idx, row in enumerate(table[:5]):
                    # Upper case and strip
                    row_texts = [str(c).upper().strip() if c else "" for c in row]
                    if "DATE" in row_texts and "TIME" in row_texts:
                        header_row = row_texts
                        header_idx = idx
                        break
                
                if header_row:
                    try:
                        date_col_idx = header_row.index("DATE")
                        time_col_idx = header_row.index("TIME")
                        
                        # Identify Subject Columns
                        subject_cols = []
                        for c_idx, col_name in enumerate(header_row):
                            if c_idx not in [date_col_idx, time_col_idx] and col_name and "DAY" not in col_name:
                                subject_cols.append((c_idx, col_name))
                        
                        current_date = None
                        
                        # Iterate Data Rows
                        for row_idx in range(header_idx + 1, len(table)):
                            row = table[row_idx]
                            row = [str(cell).strip() if cell else "" for cell in row]
                            
                            if len(row) <= max(date_col_idx, time_col_idx): continue
                            
                            date_val = row[date_col_idx]
                            time_val = row[time_col_idx]
                            
                            # Skip Section Headers
                            if "MSE" in date_val.upper() or "EXAM" in date_val.upper():
                                continue

                            # Handle Date
                            if any(c.isdigit() for c in date_val):
                                current_date = date_val
                            
                            # Use current date if this row has no date but has valid time (merged)
                            d_to_use = date_val if date_val else current_date
                            
                            if not d_to_use or not time_val or len(time_val) < 4:
                                continue
                                
                            # Extract Subjects
                            for (subj_idx, stream_name) in subject_cols:
                                if subj_idx < len(row):
                                    subj_text = row[subj_idx]
                                    # Filter invalid placeholder "----"
                                    if len(subj_text) > 2 and "---" not in subj_text:
                                        subj_clean = subj_text.replace('\n', ' ')
                                        final_subject = f"{subj_clean} ({stream_name})"
                                        
                                        sessions.append({
                                            "date": d_to_use,
                                            "time": time_val,
                                            "subject": final_subject
                                        })
                    except ValueError:
                        pass
                        
                else:
                    # --- STRATEGY 2: Legacy Fallback (Position Based) ---
                    # Used for TT_SEM5_R_2023.pdf
                    for row in table:
                        row = [str(cell).strip() if cell else "" for cell in row]
                        
                        # Needs at least Date, Time, Subject
                        if len(row) < 3: continue
                        
                        date_val = row[0]
                        time_val = row[1]
                        
                        # Subject is usually the last column or specific index
                        # In the observed 4-col rows: Date, Time, Code, Subject
                        # In 6-col rows: Date, Time, ..., Subject
                        subj_val = row[-1]
                        
                        # Verify Date format (Simple digit check or length)
                        if len(date_val) > 4 and any(c.isdigit() for c in date_val) and "Date" not in date_val:
                             # Verify Subject (not empty, not too short)
                             if len(subj_val) > 2:
                                 # Avoid duplicate headers if they sneak in
                                 if "Subject" in subj_val or "Paper" in subj_val: continue
                                 
                                 sessions.append({
                                    "date": date_val,
                                    "time": time_val,
                                    "subject": subj_val
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
        # Save to Excel
        df.to_excel(excel_path, index=False, header=False)
        print(f"Successfully extracted {len(all_data)} rows to {excel_path}")
    else:
        print("No tabular data found in the PDF.")