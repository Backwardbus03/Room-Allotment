
from extract_pdf import normalize_date, normalize_time

dates = [
    "02/02/2026", 
    "06 November 2025",
    "31 December 2025",
    "Invalid Date"
]

times = [
    "10.15 a.m. to 11.00 a.m.",
    "11.15 am to 01.15 pm",
    "9.30 a.m. to 10.15 a.m.",
    "10:15 am",
    "01.00 pm"
]

print("--- Testing Date Normalization ---")
for d in dates:
    print(f"'{d}' -> '{normalize_date(d)}'")

print("\n--- Testing Time Normalization ---")
for t in times:
    print(f"'{t}' -> '{normalize_time(t)}'")
