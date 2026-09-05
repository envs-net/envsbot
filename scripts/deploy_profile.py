"""envsbot deployment profile for envs-xmpp."""
from envs_xmpp_ops.profile import DeploymentProfile

PROFILE = DeploymentProfile(
    app_name="envsbot",
    executable="envsbot",
    service_name="envsbot.service",
    config_environment="ENVSBOT_CONFIG",
    default_config="/etc/envsbot/config.py",
    default_data="/var/lib/envsbot",
    service_user="envsbot",
    service_group="envsbot",
    venv_name=".venv",
)
