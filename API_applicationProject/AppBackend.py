import os
import PyPDF2
import io
from flask import Flask, request, jsonify, render_template
from google import genai
from dotenv import load_dotenv


# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), "ENVIRONMENT_variables.env")
load_dotenv(env_path, override=True)

app = Flask(__name__, template_folder='templates', static_folder='static')

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
        client = genai.Client(api_key=os.getenv('API_KEY'))
        
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
        )
        
        # Return the generated JSON
        return jsonify({
            'success': True,
            'study_guide': response.text
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