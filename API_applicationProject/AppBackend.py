import os
import PyPDF2
import io
import requests
from urllib.parse import urlencode
from flask import Flask, request, jsonify, render_template, redirect, session, url_for
from google import genai
from dotenv import load_dotenv
from Googler.security import generate_state, generate_pkce_pair
from GoogleDocCreator import generate_doc_from_json


# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), "ENVIRONMENT_variables.env")
load_dotenv(env_path, override=True)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.secret_key = os.getenv("GOOGLE_CLIENT_SECRET", "dev-secret-key-change-me")

# Google OAuth configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:5001/auth/google/callback")

def promptAPI(prompt):
    client = genai.Client(api_key=os.getenv('API_KEY'))
        
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

def extract_text_from_pdf(pdf_file):
    """Extract text from uploaded PDF file"""
    try:
        pdf_reader = PyPDF2.PdfReader(pdf_file)
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error extracting text from PDF: {str(e)}"


@app.route("/create_google_doc", methods=["POST"])
def create_google_doc():
    """
    Create a Google Doc from the generated study guide JSON.
    Expects JSON body:
      {
        "study_guide": { ... },   # the parsed guide JSON
        "additional_requests": "optional extra instructions for doc layout"
      }

    Requires the user to be logged in with Google so that a refresh token /
    access token is available in the session.
    """
    user = session.get("user")
    if not user:
        return jsonify({"success": False, "error": "User not authenticated with Google"}), 401

    data = request.get_json(silent=True) or {}
    study_guide = data.get("study_guide")
    additional_requests = data.get("additional_requests", "").strip()

    if not study_guide:
        return jsonify({"success": False, "error": "Missing study_guide data"}), 400

    # Attach additional instructions into the JSON so they appear in the doc
    if additional_requests:
        study_guide["additional_doc_requests"] = additional_requests

    # In a real app you should store and use a long-lived refresh token.
    # For simplicity here, we expect a refresh token or access token to be
    # available in the session. Adapt as needed for your token model.
    refresh_token = user.get("access_token")
    if not refresh_token:
        return jsonify({"success": False, "error": "Missing refresh token for Google Docs access"}), 400

    try:
        result = generate_doc_from_json(
            json_data=study_guide,
            refresh_token=refresh_token,
            create_folder_flag=True,
            folder_name="Generated Study Guides"
        )
        return jsonify({"success": True, "doc_url": result.get("doc_url")}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/auth/google")
def google_login():
    """
    Redirect the user to Google's OAuth 2.0 endpoint using PKCE.
    """
    if not GOOGLE_CLIENT_ID:
        return jsonify({"error": "Missing GOOGLE_CLIENT_ID in environment"}), 500

    state = generate_state()
    code_verifier, code_challenge = generate_pkce_pair()

    # Store values in session for later verification
    session["oauth_state"] = state
    session["code_verifier"] = code_verifier

    query_params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/documents https://www.googleapis.com/auth/drive",
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = f"{GOOGLE_AUTH_ENDPOINT}?{urlencode(query_params)}"
    return redirect(auth_url)


@app.route("/auth/google/callback")
def google_callback():
    """
    Handle Google's OAuth 2.0 callback, exchange code for tokens,
    fetch basic user info, and store it in the session.
    """
    error = request.args.get("error")
    if error:
        return jsonify({"error": error}), 400

    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state:
        return jsonify({"error": "Missing code or state in callback"}), 400

    # Validate state
    session_state = session.get("oauth_state")
    if not session_state or state != session_state:
        return jsonify({"error": "Invalid OAuth state"}), 400

    code_verifier = session.get("code_verifier")
    if not code_verifier:
        return jsonify({"error": "Missing PKCE verifier in session"}), 400

    # Exchange authorization code for tokens
    token_payload = {
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": app.secret_key,
        "code": code,
        "code_verifier": code_verifier,
        "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_REDIRECT_URI,
    }

    token_resp = requests.post(GOOGLE_TOKEN_ENDPOINT, data=token_payload)
    if token_resp.status_code != 200:
        return jsonify({"error": "Failed to exchange code for tokens", "details": token_resp.text}), 400

    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    id_token = token_data.get("id_token")

    # Clear one-time values
    session.pop("oauth_state", None)
    session.pop("code_verifier", None)

    if not access_token:
        return jsonify({"error": "No access token received from Google"}), 400

    # Fetch user info
    userinfo_resp = requests.get(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
    )

    if userinfo_resp.status_code != 200:
        return jsonify({"error": "Failed to fetch user info", "details": userinfo_resp.text}), 400

    userinfo = userinfo_resp.json()

    # Store minimal login info in session
    session["user"] = {
        "email": userinfo.get("email"),
        "name": userinfo.get("name"),
        "picture": userinfo.get("picture"),
        "access_token": access_token,
        "id_token": id_token,
    }

    # Redirect back to the main page; frontend can call /api/me to check login state
    return redirect(url_for("index"))


@app.route("/api/me")
def current_user():
    """
    Simple endpoint to get the currently logged in user (if any).
    Does NOT expose tokens in a real app; here included for demonstration.
    """
    user = session.get("user")
    if not user:
        return jsonify({"authenticated": False}), 200

    # In production, do NOT return access_token/id_token to the frontend.
    return jsonify({"authenticated": True, "user": user}), 200

@app.route('/generate_study_guide', methods=['POST'])
def generate_study_guide():
    try:
        # Check if request contains files (multipart/form-data) or JSON
        if request.files:
            # Get form data and files
            user = request.form.get('user', 'not specified (student)')
            subject = request.form.get('subject')
            purpose = request.form.get('purpose', 'not specified (study for an upcoming exam)')
            topics_subsections = request.form.get('topics_subsections', 'not specified (none)')
            other_specifications = request.form.get('other_specifications', 'not specified (none)')
            length = request.form.get('length', 'not specified')
            content = request.form.get('content', 'not specified')
            
            # Handle PDF file if uploaded
            material = 'not specified (none)'
            if 'material' in request.files:
                pdf_file = request.files['material']
                if pdf_file.filename:
                    pdf_text = extract_text_from_pdf(pdf_file)
                    material = f"Uploaded PDF content:\n{pdf_text[:5000]}"  # Limit to first 5000 chars
        else:
            # Get JSON data
            data = request.get_json()
            user = data.get('user', 'not specified (student)')
            subject = data.get('subject')
            purpose = data.get('purpose', 'not specified (study for an upcoming exam)')
            topics_subsections = data.get('topics_subsections', 'not specified (none)')
            material = data.get('material', 'not specified (none)')
            other_specifications = data.get('other_specifications', 'not specified (none)')
            length = data.get('length', 'not specified')
            content = data.get('content', 'not specified')

        # Validate that required parameters are provided
        if not all([subject]):
            return jsonify({
                'error': 'Missing required parameters. Required: subject. Optional: user, purpose, topics_subsections, material, other_specifications, length, content'
            }), 400
        
        # Read the template file
        template_path = os.path.join(os.path.dirname(__file__), "prompt_template.txt")
        with open(template_path, 'r') as file:
            template_content = file.read()
        
        # Replace the 8 variables in the template
        prompt = template_content.format(
            user=user,
            subject=subject,
            purpose=purpose,
            **{"topics/subsections": topics_subsections},
            material=material,
            **{"other specifications or preferences": other_specifications},
            length=length,
            content=content
        )
        
        # Generate content using Gemini API
        response = promptAPI(prompt)
        
        # Return the generated JSON
        return jsonify({
            'success': True,
            'study_guide': response
        }), 200
        
    except FileNotFoundError:
        return jsonify({
            'error': 'Template file not found'
        }), 500
    except Exception as e:
        return jsonify({
            'error': f'An error occurred: {str(e)}'
        }), 500

@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)