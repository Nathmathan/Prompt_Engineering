from google import genai
from google.genai import types

client = genai.Client(
    api_key='',
    http_options=types.HttpOptions(api_version='v1alpha')
)

response = client.models.generate_content(
    model='gemini-2.5-flash',
    contents="Explain how AI works",
)

print(response.text)