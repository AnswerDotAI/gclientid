__version__ = "0.1.2"



from .projects import create_project, delete_project
from .oauth import GMAIL_SCOPE, authorize_gmail, connect_browser, create_gmail_client
