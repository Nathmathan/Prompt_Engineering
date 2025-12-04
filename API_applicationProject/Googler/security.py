import base64
import hashlib
import os

def generate_state():
    state = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').replace('=', '')
    return state

def generate_pkce_pair():
    code_verifier = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').replace('=', '')

    code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode('utf-8').replace('=', '')
    return code_verifier, code_challenge



def generate_nonce():
    nonce = base64.urlsafe_b64encode(os.urandom(32)).decode('utf-8').replace('=', '')
    return nonce

def generate_code_challenge(code_verifier):
    code_challenge = hashlib.sha256(code_verifier.encode('utf-8')).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode('utf-8').replace('=', '')
    return code_challenge