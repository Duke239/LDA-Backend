import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr
import logging
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        # Use a simple SMTP configuration - since we only need notifications
        # We'll use a mock service that logs to console for now
        self.company_name = os.getenv("COMPANY_NAME", "LDA Group")
        self.company_email = os.getenv("COMPANY_EMAIL", "info@ldagroup.co.uk")
        self.notification_email = "info@ldagroup.co.uk"
        
    async def send_quote_response_notification(
        self,
        quote_number: str,
        client_name: str,
        client_email: str,
        response_type: str,
        client_comments: Optional[str] = None
    ) -> bool:
        """Send notification email about quote response to info@ldagroup.co.uk"""
        try:
            subject = f"Quote Response: {response_type.title()} - {quote_number}"
            
            body_text = f"""Quote Response Notification

Quote Details:
- Quote Number: {quote_number}
- Client: {client_name} ({client_email})
- Response: {response_type.upper()}
- Response Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

Client Comments:
{client_comments or 'No comments provided'}

---
This is an automated notification from the LDA Group Quote System.
Please follow up with the client at: {client_email}

Best regards,
LDA Group Quote System"""
            
            # For now, just log the email content (no actual SMTP sending)
            logger.info(f"EMAIL NOTIFICATION TO {self.notification_email}:")
            logger.info(f"Subject: {subject}")
            logger.info(f"Body: {body_text}")
            
            # TODO: Replace with actual SMTP when credentials are available
            print(f"\n=== EMAIL NOTIFICATION ===")
            print(f"TO: {self.notification_email}")
            print(f"SUBJECT: {subject}")
            print(f"BODY:\n{body_text}")
            print(f"=========================\n")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to send quote response notification: {str(e)}")
            return False
    
    async def _send_email(self, message: MIMEMultipart, recipient: str):
        """Send email via SMTP"""
        try:
            # Create SMTP connection
            server = smtplib.SMTP(self.smtp_server, self.smtp_port)
            server.set_debuglevel(0)
            
            # Start TLS if enabled
            if self.use_tls:
                context = ssl.create_default_context()
                server.starttls(context=context)
            
            # Login and send email
            server.login(self.username, self.password)
            server.send_message(message)
            server.quit()
            
            logger.info(f"Email sent successfully to {recipient}")
            
        except Exception as e:
            logger.error(f"SMTP error: {str(e)}")
            raise

    async def send_notification_email(
        self,
        recipient_email: str,
        subject: str,
        body: str
    ) -> bool:
        """Send a simple notification email"""
        try:
            message = MIMEMultipart()
            message["From"] = formataddr((self.company_name, self.company_email))
            message["To"] = recipient_email
            message["Subject"] = subject
            
            message.attach(MIMEText(body, "plain"))
            
            await self._send_email(message, recipient_email)
            return True
            
        except Exception as e:
            logger.error(f"Failed to send notification email: {str(e)}")
            return False