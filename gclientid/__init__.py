__version__ = "0.1.3"




from .projects import create_project, delete_project
from .config import config_dir, oauth_settings
from .oauth import CLOUD_SCOPES, GMAIL_SCOPE, GOOGLE_APPS_SCOPES, PRESETS, WORKSPACE_ADMIN_SCOPES
from .oauth import authorize_google, connect_browser, create_client, oauth_config
