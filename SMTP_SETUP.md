# How to Configure Email (SMTP)

To enable the mailing feature, you need to provide SMTP credentials. The easiest way to test this is using a **Gmail** account with an **App Password**.

## Option 1: Gmail (Recommended for Testing)

Google does not allow you to use your login password directly for security reasons. You must generate an "App Password".

### Steps:
1.  Go to your [Google Account Settings](https://myaccount.google.com/).
2.  Navigate to **Security**.
3.  Under "How you sign in to Google", ensure **2-Step Verification** is turned **ON**. (This is required).
4.  Once 2FA is on, search for **"App passwords"** in the top search bar (or go to [https://myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)).
5.  **Create a new App Password**:
    *   **App name**: Enter "Exam Scheduler" (or any name).
    *   Click **Create**.
6.  Google will show you a 16-character password (e.g., `abcd efgh ijkl mnop`). **Copy this password.**

### update your `.env` file:
Open your `.env` file in the project directory and add the following lines:

```env
# Email Settings
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USE_TLS=True
MAIL_USERNAME=your.email@gmail.com
MAIL_PASSWORD=abcd efgh ijkl mnop
```
*(Replace `your.email@gmail.com` with your actual email and the password with your generated App Password. Spaces in the password don't matter).*

---

## Option 2: Ethereal Email (Fake Inbox for Developers)
If you don't want to use a real account, you can use Ethereal.email to catch emails in a fake inbox.

1.  Go to [Ethereal.email](https://ethereal.email/) and click "Create Ethereal Account".
2.  It will give you `user` and `pass` credentials.
3.  Update `.env`:
    ```env
    MAIL_SERVER=smtp.ethereal.email
    MAIL_PORT=587
    MAIL_USE_TLS=True
    MAIL_USERNAME=your_ethereal_user@ethereal.email
    MAIL_PASSWORD=your_ethereal_password
    ```
