import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from threading import Thread
from flask import current_app
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from email.mime.application import MIMEApplication

# ... (logging config existing) ...
logger = logging.getLogger(__name__)

def send_async_email(app, msg):
    with app.app_context():
        try:
            print(f"[MAIL DEBUG] Connecting to SMTP: {app.config['MAIL_SERVER']}:{app.config['MAIL_PORT']}")
            server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'])
            server.set_debuglevel(1) # verbose on console
            if app.config['MAIL_USE_TLS']:
                server.starttls()
            
            if app.config.get('MAIL_USERNAME') and app.config.get('MAIL_PASSWORD'):
                server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
            
            server.send_message(msg)
            server.quit()
            print(f"[MAIL DEBUG] Email sent successfully to {msg['To']}")
            logger.info(f"Email sent to {msg['To']}")
        except Exception as e:
            print(f"[MAIL DEBUG] FAILED to send email to {msg['To']}: {e}")
            logger.error(f"Failed to send email: {e}")

# ... (test_email_connection existing) ...

def send_email(subject, recipient, html_body, attachments=None):
    """
    attachments: list of dicts {'filename': str, 'data': bytes, 'content_type': str}
    """
    print(f"[MAIL DEBUG] Preparing email '{subject}' to {recipient}")
    app = current_app._get_current_object()
    
    msg = MIMEMultipart()
    msg['Subject'] = subject
    msg['From'] = app.config['MAIL_DEFAULT_SENDER']
    msg['To'] = recipient
    
    msg.attach(MIMEText(html_body, 'html'))
    
    if attachments:
        print(f"[MAIL DEBUG] Attaching {len(attachments)} files...")
        for att in attachments:
            part = MIMEApplication(att['data'], Name=att['filename'])
            part['Content-Disposition'] = f'attachment; filename="{att["filename"]}"'
            msg.attach(part)
    
    thr = Thread(target=send_async_email, args=[app, msg])
    thr.start()
    return thr

def format_schedule_table(schedule_rows):
    """
    Helper to format a list of schedule dictionaries into an HTML table.
    Expects keys: Date, Time, Block, Role, Subject (optional)
    """
    if not schedule_rows:
        return "<p>No duties assigned.</p>"
        
    html = """
    <table border="1" cellpadding="5" cellspacing="0" style="border-collapse: collapse; width: 100%;">
        <thead>
            <tr style="background-color: #f2f2f2;">
                <th>Date</th>
                <th>Time</th>
                <th>Block</th>
                <th>Role</th>
                <th>Subject</th>
            </tr>
        </thead>
        <tbody>
    """
    
    for row in schedule_rows:
        html += f"""
        <tr>
            <td>{row.get('Date', '')}</td>
            <td>{row.get('Time', '')}</td>
            <td>{row.get('Block', '')}</td>
            <td>{row.get('Role', '')}</td>
            <td>{row.get('Subject', '')}</td>
        </tr>
        """
        
    html += "</tbody></table>"
    return html

def send_schedule_notification(supervisor_email, supervisor_name, exam_name, schedule_rows, pdf_bytes=None):
    subject = f"Exam Duty Schedule - {exam_name}"
    
    table_html = format_schedule_table(schedule_rows)
    
    html_body = f"""
    <html>
    <body>
        <p>Dear {supervisor_name},</p>
        <p>The schedule for <strong>{exam_name}</strong> has been generated.</p>
        <p>Your assigned duties are as follows:</p>
        {table_html}
        <p>Please log in to the portal for more details.</p>
        <p>Regards,<br>Exam Cell</p>
    </body>
    </html>
    """
    
    attachments = []
    if pdf_bytes:
        attachments.append({
            'filename': f"{exam_name}_{supervisor_name}_Schedule.pdf".replace(" ", "_"),
            'data': pdf_bytes,
            'content_type': 'application/pdf'
        })
    
    send_email(subject, supervisor_email, html_body, attachments)

def send_issue_reported_notification(admin_email, exam_name, supervisor_name, issue_details):
    subject = f"New Issue Reported - {exam_name}"
    
    html_body = f"""
    <html>
    <body>
        <p><strong>Issue Reported</strong></p>
        <p><strong>Exam:</strong> {exam_name}</p>
        <p><strong>Supervisor:</strong> {supervisor_name}</p>
        <p><strong>Details:</strong> {issue_details}</p>
        <p>Please log in to the Admin Dashboard to resolve this.</p>
    </body>
    </html>
    """
    send_email(subject, admin_email, html_body)

def send_admin_schedule_notification(admin_email, exam_name, pdf_bytes, update_type="Generated"):
    subject = f"Master Schedule {update_type} - {exam_name}"
    
    html_body = f"""
    <html>
    <body>
        <p>The Master Schedule for <strong>{exam_name}</strong> has been {update_type.lower()}.</p>
        <p>Please find the full schedule attached.</p>
    </body>
    </html>
    """
    
    attachments = []
    if pdf_bytes:
        attachments.append({
            'filename': f"{exam_name}_Master_Schedule.pdf".replace(" ", "_"),
            'data': pdf_bytes,
            'content_type': 'application/pdf'
        })
        
    send_email(subject, admin_email, html_body, attachments)

def send_swap_rejection(supervisor_email, supervisor_name, exam_name, reason):
    subject = f"Duty Swap Request Rejected - {exam_name}"
    
    html_body = f"""
    <html>
    <body>
        <p>Dear {supervisor_name},</p>
        <p>Your request to swap a duty for <strong>{exam_name}</strong> has been <span style="color: red; font-weight: bold;">REJECTED</span> by the Admin.</p>
        <p><strong>Reason:</strong> {reason}</p>
        <p>Please contact the Exam Cell if you have further questions.</p>
        <p>Regards,<br>Exam Cell</p>
    </body>
    </html>
    """
    
    send_email(subject, supervisor_email, html_body)

def send_swap_acceptance(supervisor_A_email, supervisor_A_name, supervisor_B_email, supervisor_B_name, exam_name, schedule_A, schedule_B):
    """
    Sends updated schedule to BOTH supervisors A and B.
    """
    
    # Email to Supervisor A
    subject_A = f"Duty Swap Request Accepted - {exam_name}"
    table_A = format_schedule_table(schedule_A)
    body_A = f"""
    <html>
    <body>
        <p>Dear {supervisor_A_name},</p>
        <p>Your duty swap request for <strong>{exam_name}</strong> has been <span style="color: green; font-weight: bold;">ACCEPTED</span>.</p>
        <p>Swap was confirmed with <strong>{supervisor_B_name}</strong>.</p>
        <p>Your updated schedule is below:</p>
        {table_A}
        <p>Regards,<br>Exam Cell</p>
    </body>
    </html>
    """
    send_email(subject_A, supervisor_A_email, body_A)
    
    # Email to Supervisor B
    subject_B = f"Duty Swap Request Accepted - {exam_name}"
    table_B = format_schedule_table(schedule_B)
    body_B = f"""
    <html>
    <body>
        <p>Dear {supervisor_B_name},</p>
        <p>A duty swap request involving you for <strong>{exam_name}</strong> has been <span style="color: green; font-weight: bold;">ACCEPTED</span>.</p>
        <p>Swap was confirmed with <strong>{supervisor_A_name}</strong>.</p>
        <p>Your updated schedule is below:</p>
        {table_B}
        <p>Regards,<br>Exam Cell</p>
    </body>
    </html>
    """
    send_email(subject_B, supervisor_B_email, body_B)
