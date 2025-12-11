import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

env_path = os.path.join(os.path.dirname(__file__), "ENVIRONMENT_variables.env")
load_dotenv(env_path, override=True)

def get_clients(refresh_token):
    creds = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=os.getenv('GOOGLE_CLIENT_ID'),
        client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
        scopes=["https://www.googleapis.com/auth/documents",
                "https://www.googleapis.com/auth/drive"]
    )
    return (
        build("docs", "v1", credentials=creds),
        build("drive", "v3", credentials=creds)
    )
def create_doc(drive, title):
    file_metadata = {
        "name": title,
        "mimeType": "application/vnd.google-apps.document"
    }
    file = drive.files().create(body=file_metadata, fields="id").execute()
    return file["id"]

SEMANTIC_OBJECT_KEYS = {"title", "definition", "examples", "implications", "additional_notes"}

def is_semantic_object(obj: dict) -> bool:
    return any(key in obj for key in SEMANTIC_OBJECT_KEYS)

def json_to_doc_requests(data, start_index=1, heading_level=1, section_title=None, semantic_object=False):
    """
    Build a list of Google Docs API requests to render the provided JSON.
    Returns a tuple of (requests_list, next_index).
    """
    requests = []
    index = start_index

    def insert_text(text):
        nonlocal index
        requests.append({
            "insertText": {
                "location": {"index": index},
                "text": text
            }
        })
        index += len(text)

    def add_heading(text, level):
        insert_text(text + "\n")
        requests.append({
            "updateParagraphStyle": {
                "range": {
                    "startIndex": index - len(text) - 1,
                    "endIndex": index
                },
                "paragraphStyle": {
                    "namedStyleType": f"HEADING_{min(level, 6)}"
                },
                "fields": "namedStyleType"
            }
        })

    def add_bullet_list(items):
        nonlocal index
        block = "\n".join(f"- {item}" for item in items) + "\n"
        start = index
        insert_text(block)
        requests.append({
            "createParagraphBullets": {
                "range": {"startIndex": start, "endIndex": index},
                "bulletPreset": "BULLET_DISC_CIRCLE_SQUARE"
            }
        })

    # ---- MAIN LOGIC ----
    if isinstance(data, dict):

        # Print section title if provided
        if section_title:
            add_heading(section_title, heading_level)

        for key, value in data.items():
            # If this dict is a semantic object (e.g., has "title") and we've
            # already used the title as a heading, skip rendering the raw title
            if semantic_object and key == "title":
                continue
            formatted_key = key.replace("_", " ").title()
            child_title = formatted_key

            child_reqs, index = json_to_doc_requests(
                value,
                index,
                heading_level + 1,
                section_title=child_title
            )
            requests.extend(child_reqs)

    elif isinstance(data, list):

        # List of dicts → semantic objects?
        if data and all(isinstance(x, dict) for x in data):
            if all(is_semantic_object(x) for x in data):
                # Treat each as a subsection instead of table
                for obj in data:
                    child_reqs, index = json_to_doc_requests(
                        obj,
                        index,
                        heading_level + 1,
                        section_title=obj.get("title", "Item"),
                        semantic_object=True
                    )
                    requests.extend(child_reqs)
            else:
                # Otherwise → generate table
                headers = list(data[0].keys())
                table_rows = [headers] + [
                    [item.get(h, "") for h in headers] for item in data
                ]

                # Insert a real table using Google Docs requests
                table_start_index = index
                requests.append({
                    "insertTable": {
                        "rows": len(table_rows),
                        "columns": len(headers),
                        "location": {"index": table_start_index}
                    }
                })

                # Fill each cell by inserting text sequentially through the table content.
                # We approximate cell offsets by walking content order; this avoids invalid
                # tableCellLocation usage (not supported in insertText).
                insertion_index = table_start_index
                for row in table_rows:
                    for cell_value in row:
                        text = str(cell_value)
                        requests.append({
                            "insertText": {
                                "text": text,
                                "location": {"index": insertion_index}
                            }
                        })
                        insertion_index += len(text)
                        # Add a space to advance past the inserted text within the cell
                        insertion_index += 0

                # Advance index past the table (Docs reserves one position for the table)
                index = table_start_index + 1

        # List of primitives → bullet list
        elif all(not isinstance(x, dict) for x in data):
            add_bullet_list(data)

    else:
        # Primitives → paragraph
        insert_text(str(data) + "\n\n")
    return requests, index

def update_doc(docs, doc_id, requests):
    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests}
    ).execute()

def create_folder(drive, folder_name):
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }
    folder = drive.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def move_file_to_folder(drive, file_id, folder_id):
    file = drive.files().get(fileId=file_id, fields="parents").execute()
    previous_parents = ",".join(file.get("parents", []))

    drive.files().update(
        fileId=file_id,
        addParents=folder_id,
        removeParents=previous_parents,
        fields="id, parents"
    ).execute()

def generate_doc_from_json(
    json_data,
    refresh_token,
    create_folder_flag=False,
    folder_name=None
):
    docs, drive = get_clients(refresh_token)

    # Step 1: Create doc
    doc_id = create_doc(drive, json_data.get("subject", "New Study Guide"))

    # Step 2: Build out content
    requests, _ = json_to_doc_requests(json_data)

    # Step 3: Write the content
    update_doc(docs, doc_id, requests)

    # Step 4: Optional folder placement
    folder_id = None
    if create_folder_flag:
        folder_id = create_folder(drive, folder_name or "Generated Study Guides")
        move_file_to_folder(drive, doc_id, folder_id)

    return {
        "requests":requests,
        "doc":docs,
        "doc_id": doc_id,
        "doc_url": f"https://docs.google.com/document/d/{doc_id}/edit",
        "folder_id": folder_id
    }
