"""Fetch id_token from OIDC IDP and exchange it for temporary AWS credentials."""

import base64
import hashlib
import logging
import os
import queue
import secrets
import string
import webbrowser
from threading import Thread

import boto3
import flask.cli
import requests
from ansible.plugins.callback import CallbackBase
from flask import Flask, make_response, render_template_string, request

LOCAL_CALLBACK_PORT = os.environ.get("LOCAL_CALLBACK_PORT", "8080")
IDP_AUTH_URL = os.environ.get("IDP_AUTH_URL", "https://idm.example.com/ui/oauth2")
IDP_TOKEN_URL = os.environ.get("IDP_TOKEN_URL", "https://idm.example.com/oauth2/token")
IDP_CLIENT_ID = os.environ.get("IDP_CLIENT_ID", "ansible-aws")
IDP_REDIRECT_URI = os.environ.get(
    "IDP_REDIRECT_URI", f"http://localhost:{LOCAL_CALLBACK_PORT}/callback"
)

RESPONSE_TYPE = "code"
SCOPE = "openid"
CODE_VERIFIER = "".join(
    secrets.choice(string.ascii_letters + string.digits + "-._~") for _ in range(128)
)
CODE_CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(CODE_VERIFIER.encode("utf-8")).digest())
    .rstrip(b"=")
    .decode("utf-8")
)
STATE = secrets.token_urlsafe(16)

AWS_ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "123456789")
AWS_IAM_ROLE_NAME = os.environ.get("AWS_IAM_ROLE_NAME", "iam-identity-provider-idm.example.com")
ROLE_ARN = f"arn:aws:iam::{AWS_ACCOUNT_ID}:role/{AWS_IAM_ROLE_NAME}"

PID = os.getpid()
app = Flask(__name__)
# disable all the noisy logging
app.logger.setLevel(logging.ERROR)
flask.cli.show_server_banner = lambda *args: None
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

aws_credentials = queue.Queue()


@app.route("/callback")
def callback():
    """Target for the IDP redirect to receive the id_token."""

    returned_state = request.args.get("state")
    if returned_state != STATE:
        return "State parameter mismatch", 400

    authorization_code = request.args.get("code")
    if not authorization_code:
        return "Authorization code not found", 400

    token_endpoint = IDP_TOKEN_URL
    token_data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": IDP_REDIRECT_URI,
        "client_id": IDP_CLIENT_ID,
        "code_verifier": CODE_VERIFIER,
    }

    response = requests.post(token_endpoint, data=token_data, timeout=10)
    token_response = response.json()

    id_token = token_response.get("id_token")
    if not id_token:
        return "ID Token not found in the response", 400

    credentials = exchange_token_for_aws(id_token)
    aws_credentials.put(credentials)

    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>IDP Authentication Succeeded</title>
        <script type="text/javascript">
            function closeTab() {
                setTimeout(function() {
                    window.open('','_self').close();
                }, 3000);
            }
        </script>
    </head>
    <body onload="closeTab()">
        IDP authentication succeeded. Close me or I will.
    </body>
    </html>
    """
    return make_response(render_template_string(html_content))


def exchange_token_for_aws(id_token):
    """Visit AWS API to exchange received IDP id_token for temporary AWS token."""

    client = boto3.client("sts")
    response = client.assume_role_with_web_identity(
        RoleArn=ROLE_ARN,
        RoleSessionName="web-identity-session",
        WebIdentityToken=id_token,
    )

    return response["Credentials"]


class CallbackModule(CallbackBase):
    """Ansible callback that fetches temporary AWS credentials for use within the playbook run."""

    CALLBACK_VERSION = 1.0
    CALLBACK_TYPE = "authentication"
    CALLBACK_NAME = "aws_token_fetcher"

    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()

    def v2_playbook_on_start(self, playbook):
        self.authenticate_user()
        self.set_environment_variables()

    def authenticate_user(self):
        """Send the user to the IDP in a browser and serve callback endpoint."""

        webbrowser.open(
            (
                f"{IDP_AUTH_URL}?client_id={IDP_CLIENT_ID}"
                f"&redirect_uri={IDP_REDIRECT_URI}&response_type={RESPONSE_TYPE}"
                f"&scope={SCOPE}&code_challenge={CODE_CHALLENGE}&code_challenge_method=S256"
                f"&state={STATE}"
            )
        )

        thread = Thread(target=app.run, kwargs={"port": LOCAL_CALLBACK_PORT})
        thread.daemon = True
        thread.start()

    def set_environment_variables(self):
        """Expose AWS token details"""

        try:
            credentials = aws_credentials.get(timeout=10)
        except queue.Empty:
            print("Did not retrieve AWS credentials in time")
            return

        os.environ["AWS_ACCESS_KEY_ID"] = credentials["AccessKeyId"]
        os.environ["AWS_SECRET_ACCESS_KEY"] = credentials["SecretAccessKey"]
        os.environ["AWS_SESSION_TOKEN"] = credentials["SessionToken"]
