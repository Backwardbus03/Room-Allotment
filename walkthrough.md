
# Walkthrough - Time Input & Extraction Updates

## Overview
Based on user request, the session time input has been split into distinct "Start Time" and "End Time" fields. This formatting is applied both to the manual input form and the PDF auto-extraction.

## Changes
### 1. PDF Extraction (`extract_pdf.py`)
- **Start & End Time Parsing**: The extractor now identifies time ranges (e.g., `10:00 am to 01:00 pm`) and splits them into two values.
- **Normalization**: Both times are normalized to 24-hour format (e.g., `10:00`, `13:00`).

### 2. UI Configuration (`configure.html`)
- **New Inputs**: Replaced the single "Time Slot" text field with two native time pickers: `Start Time` and `End Time`.
- **Display**: The session list now displays the time as `Start - End` (e.g., `10:00 - 13:00`).
- **Auto-Population**: Uploaded PDF data automatically fills these separate fields.

### 3. Backend Logic (`app.py`)
- **Data Handling**: The server now accepts `start_time` and `end_time` from the form.
- **Scheduling**: These are combined (e.g., `10:00 - 13:00`) to create a unique identifier for the time slot, ensuring sessions with the same time range are scheduled together.

## User Action
- Upload your timetable PDF.
- Verify that "Start Time" and "End Time" columns in the table are populated correctly.
- Add new sessions using the split inputs.
