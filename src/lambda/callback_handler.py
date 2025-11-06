import json
import boto3
import hashlib
import requests
import os
import logging
from urllib.parse import urlparse, parse_qs, urlencode
from datetime import datetime

# Configure logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize AWS clients
secretsmanager = boto3.client('secretsmanager')

# Fyers API endpoints
FYERS_AUTH_URL = "https://api-t1.fyers.in/api/v3/generate-authcode"
FYERS_TOKEN_URL = "https://api-t1.fyers.in/api/v3/validate-authcode"

def lambda_handler(event, context):
    """
    Handles the entire Fyers OAuth2 flow automatically.
    
    1. GET (no auth_code): Redirects user to Fyers login.
    2. GET (with auth_code): Fyers redirects here. We exchange the 
       code for tokens and store them in AWS Secrets Manager.
    """
    
    # Set CORS headers for all responses
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type',
        'Access-Control-Allow-Methods': 'GET,OPTIONS'
    }

    try:
        http_method = event.get('httpMethod', 'GET')
        
        # Handle OPTIONS request for CORS preflight
        if http_method == 'OPTIONS':
            return {
                'statusCode': 200,
                'headers': headers,
                'body': json.dumps({'message': 'CORS preflight'})
            }

        # Handle GET request - this is the only method we need
        if http_method == 'GET':
            query_params = event.get('queryStringParameters')
            
            if query_params and 'auth_code' in query_params:
                # STEP 2: Fyers has redirected back with an auth_code
                auth_code = query_params['auth_code']
                logger.info("Received auth_code, exchanging for tokens...")
                return handle_token_exchange(auth_code, headers)
            else:
                # STEP 1: User is visiting the URL, redirect to Fyers login
                logger.info("No auth_code, redirecting to Fyers login...")
                return handle_login_redirect()

        # Reject other methods
        return {
            'statusCode': 405,
            'headers': headers,
            'body': json.dumps({'error': 'Method not allowed'})
        }
        
    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'headers': {**headers, 'Content-Type': 'text/html'},
            'body': f"<html><body><h1>Error</h1><p>Internal server error: {str(e)}</p></body></html>"
        }

def handle_login_redirect():
    """
    Reads env vars and constructs the Fyers login URL,
    then returns a 302 redirect response.
    """
    try:
        # Get credentials from Lambda environment variables
        client_id = os.environ['FYERS_CLIENT_ID']
        redirect_uri = os.environ['FYERS_REDIRECT_URI']
        
        # Define parameters for the auth URL
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'state': 'login' # You can use a random string for better security
        }
        
        # Construct the full authorization URL
        auth_url = f"{FYERS_AUTH_URL}?{urlencode(params)}"
        
        # Return a 302 Redirect to the user's browser
        return {
            'statusCode': 302,
            'headers': {
                'Location': auth_url
            }
        }
        
    except KeyError as e:
        logger.error(f"Missing environment variable: {str(e)}")
        raise Exception(f"Configuration error: Missing environment variable {str(e)}")

def handle_token_exchange(auth_code, headers):
    """
    Exchanges the auth_code for tokens, generates the app hash,
    and stores the credentials in AWS Secrets Manager.
    """
    try:
        # Get credentials from Lambda environment variables
        client_id = os.environ['FYERS_CLIENT_ID']
        app_secret = os.environ['FYERS_SECRET_KEY']
        secret_name = os.environ['SECRETS_NAME']

        # 1. Generate app hash
        app_hash = hashlib.sha256(f"{client_id}:{app_secret}".encode()).hexdigest()
        
        # 2. Prepare payload for token request
        token_payload = {
            'grant_type': 'authorization_code',
            'appIdHash': app_hash,
            'code': auth_code
        }
        
        # 3. Request tokens from Fyers API
        logger.info("Requesting access token from Fyers API...")
        response = requests.post(
            FYERS_TOKEN_URL,
            json=token_payload,
            headers={'Content-Type': 'application/json'},
            timeout=30
        )
        
        response_data = response.json()
        
        if response_data.get('s') != 'ok':
            logger.error(f"Fyers API error: {response_data.get('message')}")
            raise Exception(f"Fyers API error: {response_data.get('message', 'Unknown error')}")
            
        access_token = response_data.get('access_token')
        refresh_token = response_data.get('refresh_token')
        
        if not access_token or not refresh_token:
            logger.error("Tokens not received from Fyers API")
            raise Exception('Tokens not received from Fyers API')
            
        logger.info("Successfully received tokens from Fyers.")

        # 4. Store all credentials in AWS Secrets Manager as one JSON object
        secret_data = {
            'client_id': client_id,
            'app_secret': app_secret,
            'access_token': access_token,
            'refresh_token': refresh_token,
            'last_updated': datetime.now().isoformat()
        }
        secret_string = json.dumps(secret_data, indent=4)
        
        # Use update_secret or create_secret (Update-or-Create pattern)
        try:
            secretsmanager.update_secret(
                SecretId=secret_name,
                SecretString=secret_string
            )
            logger.info(f"Successfully updated secret: {secret_name}")
        except secretsmanager.exceptions.ResourceNotFoundException:
            logger.info(f"Secret not found, creating new secret: {secret_name}")
            secretsmanager.create_secret(
                Name=secret_name,
                SecretString=secret_string,
                Description="Fyers API credentials for stock pipeline"
            )
        
        # 5. Return a success message to the user
        success_html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>✅ Success!</title>
            <style>
                body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; display: grid; place-items: center; min-height: 90vh; background-color: #f4f7f6; }
                .container { background: #fff; border-radius: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.05); padding: 40px; text-align: center; }
                h1 { color: #28a745; }
                p { font-size: 1.1em; color: #333; }
                code { background: #e9ecef; padding: 3px 6px; border-radius: 4px; }
            </style>
        </head>
        <body>
            <div class="container">
                <h1>✅ Success!</h1>
                <p>Fyers tokens have been generated and securely stored in AWS Secrets Manager.</p>
                <p>Secret Name: <code>""" + secret_name + """</code></p>
                <p>You can now close this window.</p>
            </div>
        </body>
        </html>
        """
        
        return {
            'statusCode': 200,
            'headers': {**headers, 'Content-Type': 'text/html'},
            'body': success_html
        }
        
    except requests.RequestException as e:
        logger.error(f"Error calling Fyers API: {str(e)}")
        raise Exception(f'Fyers API request failed: {str(e)}')
    except Exception as e:
        logger.error(f"Error in handle_token_exchange: {str(e)}")
        # Re-raise to be caught by the main handler
        raise e