import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'super-secret-key-change-this-in-prod'
    UPLOAD_FOLDER = os.path.join(os.getcwd(), 'data')
    ADMIN_PASSWORD = 'admin'
