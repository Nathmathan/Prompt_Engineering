import os
from google import genai
from dotenv import load_dotenv
env_path = os.path.join(os.path.dirname(__file__), "ENVIRONMENT_variables.env")
load_dotenv(env_path, override=True)

#import firebase_admin
#from firebase_admin import credentials, firestore

#cred = credentials.Certificate("firebase_key.json")
#firebase_admin.initialize_app(cred)

# Define a dictionary to hold questions by topic
api_key = os.getenv("API_KEY")
print(f"API_KEY loaded: {'*' * max(0, len(api_key) - 4) + (api_key[-4:] if api_key else 'MISSING')}")

client = genai.Client(api_key=os.getenv('API_KEY'))

response = client.models.generate_content(
    model="gemini-2.5-pro",
    contents="Explain how AI works in a few words",
)

print(response.text)