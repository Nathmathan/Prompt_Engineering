import os
from flask import Flask, request, jsonify
from google import genai
from dotenv import load_dotenv

# Load environment variables
env_path = os.path.join(os.path.dirname(__file__), "ENVIRONMENT_variables.env")
load_dotenv(env_path, override=True)

app = Flask(__name__)

@app.route('/generate_study_guide', methods=['POST'])
def generate_study_guide():
    try:
        # Get the 8 parameters from request in JSON format with default values if not provided
        data = request.get_json()

        # User parameters
        user = data.get('user', 'not specified (student)')
        subject = data.get('subject')
        purpose = data.get('purpose', 'not specified (study for an upcoming exam)')
        # Optional parameters
        topics_subsections = data.get('topics_subsections', 'not specified (none)')
        material = data.get('material', 'not specified (none)')
        other_specifications = data.get('other_specifications', 'not specified (none)')
        # Study plan parameters
        length = data.get('length', 'not specified')
        content = data.get('content', 'not specified')

        # Validate that required parameters are provided
        if not all([subject]):
            return jsonify({
                'error': 'Missing required parameters. Required: subject. Optional: user, purpose, topics_subsections, material, other_specifications, length, content'
            }), 400
        
        # Read the template file
        template_path = os.path.join(os.path.dirname(__file__), "prompt_2_template.txt")
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
def health_check():
    return jsonify({
        'status': 'Server is running',
        'endpoint': '/generate_study_guide',
        'method': 'POST'
    }), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)