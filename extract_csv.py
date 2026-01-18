import pandas as pd
import re
from datetime import datetime
from dateutil import parser as date_parser

# Import department mapping from extract_pdf
# We'll reuse the same mapping logic
DEPT_MAPPING = [
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

def normalize_date_flexible(date_str):
    """
    Parses date strings in multiple formats:
    - DD-Mon-YY (e.g., '06-Nov-25')
    - DD-MM-YYYY (e.g., '06-11-2025')
    - DD/MM/YYYY (e.g., '06/11/2025')
    - YYYY-MM-DD (ISO format)
    
    Returns date in 'YYYY-MM-DD' format for HTML input compatibility.
    """
    if not date_str or str(date_str).strip().lower() in ['', 'nan', 'none']:
        return None
    
    date_str = str(date_str).strip()
    
    try:
        # Use dateutil parser for flexibility (handles most formats automatically)
        # dayfirst=True ensures DD/MM/YYYY is parsed correctly
        dt = date_parser.parse(date_str, dayfirst=True)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError) as e:
        print(f"Warning: Could not parse date '{date_str}': {e}")
        return None

def normalize_time_range_flexible(time_str):
    """
    Parses time range strings in multiple formats:
    - 'HH.MM am to HH.MM pm' (e.g., '02.30 pm to 05.30 pm')
    - 'HH:MM am to HH:MM pm' (e.g., '10:30 am to 12:30 pm')
    - 'HH.MM a.m. to HH.MM p.m.' (with dots in meridiem)
    - 'HH:MM - HH:MM' (24-hour format)
    
    Returns tuple ('HH:MM', 'HH:MM') for start and end times in 24-hour format.
    Returns (None, None) if parsing fails.
    """
    if not time_str or str(time_str).strip().lower() in ['', 'nan', 'none']:
        return None, None
    
    time_str = str(time_str).strip().lower()
    
    # Normalize: replace periods with colons, remove extra spaces
    time_str = time_str.replace('a.m.', 'am').replace('p.m.', 'pm')
    time_str = time_str.replace('.', ':')
    
    # Pattern to match times: HH:MM followed optionally by am/pm
    # Matches: "10:30 am to 12:30 pm" or "14:30 to 17:30"
    pattern = r'(\d{1,2}):(\d{2})\s*(am|pm)?\s*(?:to|-)\s*(\d{1,2}):(\d{2})\s*(am|pm)?'
    
    match = re.search(pattern, time_str)
    
    if not match:
        print(f"Warning: Could not parse time range '{time_str}'")
        return None, None
    
    start_hour = int(match.group(1))
    start_min = int(match.group(2))
    start_meridiem = match.group(3)
    
    end_hour = int(match.group(4))
    end_min = int(match.group(5))
    end_meridiem = match.group(6)
    
    # Convert to 24-hour format
    if start_meridiem == 'pm' and start_hour != 12:
        start_hour += 12
    elif start_meridiem == 'am' and start_hour == 12:
        start_hour = 0
    
    if end_meridiem == 'pm' and end_hour != 12:
        end_hour += 12
    elif end_meridiem == 'am' and end_hour == 12:
        end_hour = 0
    
    start_time = f"{start_hour:02d}:{start_min:02d}"
    end_time = f"{end_hour:02d}:{end_min:02d}"
    
    return start_time, end_time

def map_department_to_code(dept_name):
    """
    Maps full department names to short codes.
    Returns the short code if found, else returns the original name.
    """
    if not dept_name or str(dept_name).strip().lower() in ['', 'nan', 'none']:
        return ""
    
    dept_lower = str(dept_name).lower().strip()
    
    # Try to match against mapping
    for pattern, short_code in DEPT_MAPPING:
        if pattern in dept_lower:
            return short_code
    
    # If no match, return original (might be already a code)
    return dept_name.strip()

def parse_csv_timetable(df):
    """
    Parses a CSV/Excel timetable DataFrame into session data.
    
    Expected columns (flexible header detection):
    - Branch/Department
    - Dates/Date
    - Time/Time Slot
    - Course Code (optional)
    - Paper/Subject
    
    Returns list of session dictionaries with normalized data.
    """
    sessions = []
    
    # Find header row (contains keywords like 'Branch', 'Date', 'Time')
    header_row_idx = None
    for idx, row in df.iterrows():
        row_str = ' '.join(str(val).lower() for val in row.values if pd.notna(val))
        if 'branch' in row_str and 'date' in row_str and 'time' in row_str:
            header_row_idx = idx
            break
    
    if header_row_idx is None:
        print("Error: Could not find header row with 'Branch', 'Dates', 'Time' columns")
        return sessions
    
    # Set header and get data rows
    df.columns = df.iloc[header_row_idx].values
    data_rows = df.iloc[header_row_idx + 1:].reset_index(drop=True)
    
    # Identify columns (flexible matching)
    dept_col = None
    date_col = None
    time_col = None
    subject_col = None
    
    for col in df.columns:
        col_lower = str(col).lower().strip()
        if 'branch' in col_lower or 'department' in col_lower:
            dept_col = col
        elif 'date' in col_lower:
            date_col = col
        elif 'time' in col_lower:
            time_col = col
        elif 'paper' in col_lower or 'subject' in col_lower:
            subject_col = col
    
    if not all([dept_col, date_col, time_col, subject_col]):
        print(f"Error: Missing required columns. Found: dept={dept_col}, date={date_col}, time={time_col}, subject={subject_col}")
        return sessions
    
    # Process rows with carry-over logic for department
    current_dept = None
    
    for idx, row in data_rows.iterrows():
        # Skip completely empty rows
        if row.isna().all():
            continue
        
        dept_val = row[dept_col]
        date_val = row[date_col]
        time_val = row[time_col]
        subject_val = row[subject_col]
        
        # Skip section header rows (e.g., "B.E. Sem VII")
        if pd.notna(dept_val):
            dept_str = str(dept_val).strip()
            # Check if it looks like a section header (no date/time data)
            if 'sem' in dept_str.lower() or 'semester' in dept_str.lower():
                continue
            # Update current department
            if dept_str and dept_str.lower() not in ['', 'nan']:
                current_dept = dept_str
        
        # Use carry-over department if current is empty
        dept_to_use = current_dept if (pd.isna(dept_val) or str(dept_val).strip() == '') else str(dept_val).strip()
        
        # Skip if no valid date/time/subject
        if pd.isna(date_val) or pd.isna(time_val) or pd.isna(subject_val):
            continue
        
        if not dept_to_use:
            continue
        
        # Normalize data
        normalized_date = normalize_date_flexible(date_val)
        start_time, end_time = normalize_time_range_flexible(time_val)
        dept_code = map_department_to_code(dept_to_use)
        
        if normalized_date and start_time and end_time:
            sessions.append({
                'date': normalized_date,
                'start_time': start_time,
                'end_time': end_time,
                'subject': str(subject_val).strip(),
                'department': dept_code
            })
    
    return sessions

def extract_sessions_from_csv(file_path):
    """
    Main entry point for extracting session data from CSV or Excel files.
    
    Args:
        file_path: Path to .csv, .xlsx, or .xls file
    
    Returns:
        List of session dictionaries with standardized format
    """
    try:
        # Detect file type and read accordingly
        if file_path.lower().endswith('.csv'):
            df = pd.read_csv(file_path, header=None)
        elif file_path.lower().endswith(('.xlsx', '.xls')):
            df = pd.read_excel(file_path, header=None)
        else:
            print(f"Error: Unsupported file type for '{file_path}'")
            return []
        
        # Parse the timetable
        sessions = parse_csv_timetable(df)
        
        print(f"Successfully extracted {len(sessions)} sessions from CSV/Excel file")
        return sessions
        
    except Exception as e:
        print(f"Error reading CSV/Excel file '{file_path}': {e}")
        return []
