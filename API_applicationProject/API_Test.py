import os
from google import genai
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), "ENVIRONMENT_variables.env")
load_dotenv(env_path, override=True)

#import firebase_admin
#from firebase_admin import credentials, firestore

#cred = credentials.Certificate("firebase_key.json")
#firebase_admin.initialize_app(cred)

# Define local variables for template replacement
user = "a high school student"
subject = "machine learning"
purpose = "preparing for an upcoming exam"
topics_subsections = "neural networks, supervised learning, unsupervised learning"
material = "textbook chapters 1-5 and lecture notes"
other_specifications = "focus on practical examples and applications"
length = "2 weeks"
content = "practice problems, quizzes, and review sessions"

# Read the template file
template_path = os.path.join(os.path.dirname(__file__), "prompt_2_template.txt")
with open(template_path, 'r') as file:
    template_content = file.read()

# Replace the 8 variables in the template
prompt = template_content.format(
    user=user,
    subject=subject,
    purpose=purpose,
    **{"topics/subsections": topics_subsections},  # Handle special char in key
    material=material,
    **{"other specifications or preferences": other_specifications},  # Handle spaces
    length=length,
    content=content
)

client = genai.Client(api_key=os.getenv('API_KEY'))

response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents=prompt,
)

print(response.text)