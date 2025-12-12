import os
import PyPDF2
import io
import requests
import json
from datetime import datetime
from urllib.parse import urlencode
from flask import Flask, request, jsonify, render_template, redirect, session, url_for
from google import genai
from dotenv import load_dotenv
from Googler.security import generate_state, generate_pkce_pair
from GoogleDocCreator import generate_doc_from_json, update_doc


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

# Audit logging functions
def _init_audit_log():
    """Initialize audit log in session if it doesn't exist."""
    if "audit_log" not in session:
        session["audit_log"] = []

def _add_audit_entry(action_type, description, details=None, status="success"):
    """
    Add an entry to the audit log.
    
    Args:
        action_type: Type of action (e.g., "study_guide_generation", "doc_creation", "formatting")
        description: Human-readable description of what happened
        details: Optional dict with additional details
        status: "success", "error", or "info"
    """
    _init_audit_log()
    entry = {
        "timestamp": datetime.now().isoformat(),
        "action_type": action_type,
        "description": description,
        "status": status,
        "details": details or {}
    }
    session["audit_log"].append(entry)
    session.modified = True

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
        _add_audit_entry(
            "doc_creation",
            "Started creating Google Doc from study guide",
            {"subject": study_guide.get("subject", "Unknown"), "has_additional_requests": bool(additional_requests)},
            "info"
        )
        
        result = generate_doc_from_json(
            json_data=study_guide,
            refresh_token=refresh_token,
            create_folder_flag=True,
            folder_name="Generated Study Guides"
        )

        _add_audit_entry(
            "doc_creation",
            "Google Doc created successfully",
            {"doc_id": result.get("doc_id"), "doc_url": result.get("doc_url")},
            "success"
        )

        # If there are additional instructions, try to fetch and apply extra requests
        if additional_requests:
            _add_audit_entry(
                "formatting",
                "Generating formatting requests based on user instructions",
                {"instructions": additional_requests[:100] + "..." if len(additional_requests) > 100 else additional_requests},
                "info"
            )
            
            try:
                extra_requests = generate_additional_requests(result.get("requests"), additional_requests)
                _add_audit_entry(
                    "formatting",
                    f"Applied {len(extra_requests)} formatting requests to document",
                    {"request_count": len(extra_requests)},
                    "success"
                )
                update_doc(result.get("doc"), result.get("doc_id"), extra_requests)
            except Exception as format_error:
                _add_audit_entry(
                    "formatting",
                    "Failed to apply formatting requests",
                    {"error": str(format_error)},
                    "error"
                )
                # Continue even if formatting fails

        return jsonify({"success": True, "doc_url": result.get("doc_url")}), 200
    except Exception as e:
        _add_audit_entry(
            "doc_creation",
            "Failed to create Google Doc",
            {"error": str(e)},
            "error"
        )
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

@app.route("/api/audit_log", methods=["GET"])
def get_audit_log():
    """
    Retrieve the audit log for the current session.
    """
    _init_audit_log()
    return jsonify({"success": True, "log": session.get("audit_log", [])}), 200

@app.route("/api/audit_log/clear", methods=["POST"])
def clear_audit_log():
    """
    Clear the audit log for the current session.
    """
    session["audit_log"] = []
    session.modified = True
    return jsonify({"success": True}), 200

def _strip_code_fences(text: str) -> str:
    """Remove common markdown code fences around JSON."""
    cleaned = text.strip()

    # Handle fenced blocks like ```json ... ``` or ``` ... ```
    if cleaned.startswith("```json"):
        cleaned = cleaned[len("```json"):]
    elif cleaned.startswith("```"):
        cleaned = cleaned[len("```"):]

    # If there's a leading newline after the fence, drop it
    cleaned = cleaned.lstrip("\n\r")

    # Strip trailing fence
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]

    return cleaned.strip()


def _fix_color_structures(requests: list) -> list:
    """
    Fix malformed color structures in Google Docs API requests.
    Converts direct rgbColor usage to the correct nested structure.
    """
    fixed = []
    for req in requests:
        if not isinstance(req, dict):
            fixed.append(req)
            continue
        
        # Deep copy to avoid modifying original
        fixed_req = json.loads(json.dumps(req))
        
        # Check for updateTextStyle requests
        if "updateTextStyle" in fixed_req:
            text_style = fixed_req["updateTextStyle"].get("textStyle", {})
            
            # Fix foregroundColor
            if "foregroundColor" in text_style:
                fg_color = text_style["foregroundColor"]
                if isinstance(fg_color, dict) and "rgbColor" in fg_color and "color" not in fg_color:
                    # Malformed: has rgbColor directly, needs color wrapper
                    text_style["foregroundColor"] = {
                        "color": {
                            "rgbColor": fg_color["rgbColor"]
                        }
                    }
            
            # Fix backgroundColor
            if "backgroundColor" in text_style:
                bg_color = text_style["backgroundColor"]
                if isinstance(bg_color, dict) and "rgbColor" in bg_color and "color" not in bg_color:
                    # Malformed: has rgbColor directly, needs color wrapper
                    text_style["backgroundColor"] = {
                        "color": {
                            "rgbColor": bg_color["rgbColor"]
                        }
                    }
        
        # Check for updateParagraphStyle requests
        if "updateParagraphStyle" in fixed_req:
            para_style = fixed_req["updateParagraphStyle"].get("paragraphStyle", {})
            
            # Fix backgroundColor in paragraph style
            if "backgroundColor" in para_style:
                bg_color = para_style["backgroundColor"]
                if isinstance(bg_color, dict) and "rgbColor" in bg_color and "color" not in bg_color:
                    para_style["backgroundColor"] = {
                        "color": {
                            "rgbColor": bg_color["rgbColor"]
                        }
                    }
        
        fixed.append(fixed_req)
    
    return fixed


def generate_additional_requests(requests, additional_requests):
    template_path = os.path.join(os.path.dirname(__file__), "doc_prompt_template.txt")
    with open(template_path, 'r') as file:
        template_content = file.read()
        
    # Replace the 2 variables in the template
    prompt = template_content.format(
        initial_requests=requests,
        **{"other specifications or instructions": additional_requests}
    )

    _add_audit_entry(
        "ai_request",
        "Sending formatting request to AI (Gemini)",
        {"model": "gemini-2.5-flash", "prompt_length": len(prompt)},
        "info"
    )
    
    result = promptAPI(prompt)
    
    _add_audit_entry(
        "ai_response",
        "Received formatting response from AI",
        {"response_length": len(result) if result else 0},
        "success"
    )

    # Clean potential code fences then parse as JSON array of Docs requests.
    cleaned = _strip_code_fences(result or "")
    if not cleaned:
        raise ValueError("No content returned for additional requests")
    print(cleaned[:300])
    #print(cleaned.substring(0,cleaned.count))
    try:
        parsed = json.loads(cleaned)
        if not isinstance(parsed, list):
            raise ValueError("Expected a list of requests")
        # Fix any malformed color structures before returning
        return _fix_color_structures(parsed)
    except Exception as e:
        # Propagate parsing issues to the caller for clearer error handling.
        raise ValueError(f"Failed to parse additional requests JSON: {e}")

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
        _add_audit_entry(
            "ai_request",
            "Sending study guide generation request to AI (Gemini)",
            {"model": "gemini-2.5-flash", "subject": subject, "user_role": user},
            "info"
        )
        
        response = promptAPI(prompt)
        
        _add_audit_entry(
            "ai_response",
            "Received study guide from AI",
            {"response_length": len(response) if response else 0, "subject": subject},
            "success"
        )
        
        _add_audit_entry(
            "study_guide_generation",
            "Study guide generated successfully",
            {"subject": subject, "has_pdf": material != 'not specified (none)'},
            "success"
        )
        
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