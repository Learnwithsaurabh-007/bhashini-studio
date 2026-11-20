from flask import Flask, request, jsonify, send_file, render_template, Response
from flask_cors import CORS
import os
import time
import traceback
from werkzeug.utils import secure_filename
from pdf2image import convert_from_path
from PIL import Image
from docx import Document
from google import genai

app = Flask(__name__)
CORS(app)

# ==========================================
# STUDIO SECURITY CREDENTIALS
# ==========================================
AUTHORIZED_USERNAME = "Berlin"
AUTHORIZED_PASSWORD = "SAMS123"

# Paste your Gemini API key here
client = genai.Client()

UPLOAD_FOLDER = 'temp_uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

CORE_LEGAL_RULES = """
- Translate into formal Indian English appropriate for a High Court judgment/order.
- Preserve the exact legal meaning; do not add or omit anything. Retain all names, dates, sections, and legal terminology.
- Regional Context (Bihar): Translate 'Hum' exclusively as 'I' and 'Humlog' exclusively as 'We'.
- Formatting: Always format department titles explicitly as 'Office of [Name]' rather than just 'office'.
- Formatting: In administrative references, give the 'Letter No.' first, followed by the department name.
- Rigorous Verification: Always double-check wherever digits are given against the source text. Never make errors in numbers, dates, or sections.
"""

print("=======================================================")
print(" Your SECURE Internet Legal Studio is READY!")
print("=======================================================")

@app.before_request
def require_login():
    """Forces a password popup before letting anyone view the site."""
    if request.method == 'OPTIONS':
        return
    auth = request.authorization
    if not auth or auth.username != AUTHORIZED_USERNAME or auth.password != AUTHORIZED_PASSWORD:
        return Response(
            'Access Denied. You must log in to use the Bhashini Legal Studio.', 
            401, 
            {'WWW-Authenticate': 'Basic realm="Login Required"'}
        )

@app.route('/')
def home():
    """Serves the index.html website to the user after they log in."""
    return render_template('index.html')

@app.route('/api/translate', methods=['POST'])
def translate():
    try:
        original_filename = "document"
        start_page = request.form.get('start_page', type=int)
        end_page = request.form.get('end_page', type=int)
        custom_instructions = request.form.get('custom_instructions', '')
        
        images_to_process = []
        
        if 'file' in request.files:
            file = request.files['file']
            if file.filename != '':
                original_filename = os.path.splitext(secure_filename(file.filename))[0]
                filepath = os.path.join(UPLOAD_FOLDER, secure_filename(file.filename))
                file.save(filepath)
                
                if filepath.lower().endswith('.pdf'):
                    pages = convert_from_path(filepath, first_page=start_page, last_page=end_page)
                    for page in pages:
                        images_to_process.append(page.convert('RGB'))
                else:
                    img = Image.open(filepath).convert('RGB')
                    images_to_process.append(img)
                
                os.remove(filepath)
                
                # PHASE 1: OCR
                ocr_prompt = """
                Extract all text from these document pages exactly as it appears in Hindi. 
                Preserve all paragraphs, tables, indentations, and numbered lists perfectly. 
                Do NOT translate the text. Just return the extracted Hindi text with flawless layout.
                """
                
                ocr_content = [ocr_prompt] + images_to_process
                extracted_hindi = ""
                
                max_retries = 3
                retry_delay = 2
                
                for attempt in range(max_retries):
                    try:
                        ocr_response = client.models.generate_content(
                            model='gemini-3.8-flash',
                            contents=ocr_content
                        )
                        extracted_hindi = ocr_response.text
                        break
                    except Exception as e:
                        if "503" in str(e) and attempt < max_retries - 1:
                            print(f"Server Busy (503). Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            raise e

                if not extracted_hindi or not extracted_hindi.strip():
                    return jsonify({'error': 'No text found during extraction.'}), 400

                # PHASE 2: TRANSLATION
                translate_prompt = f"""
                You are a meticulous Indian High Court legal translator and editor. 
                I am providing the exact extracted Hindi text from a legal document.
                
                Translate the Hindi text into formal English.
                
                PERMANENT LEGAL RULES TO ENFORCE:
                {CORE_LEGAL_RULES}
                
                ON-THE-FLY INSTRUCTIONS FOR THIS DOCUMENT:
                {custom_instructions if custom_instructions else "None"}
                
                ORIGINAL HINDI TEXT:
                {extracted_hindi}
                
                Output ONLY the finalized, corrected English text. Preserve all paragraphs, tables, indentations, and numbered lists perfectly.
                """
                
                final_translated_text = ""
                retry_delay = 2
                
                for attempt in range(max_retries):
                    try:
                        trans_response = client.models.generate_content(
                            model='gemini-3.8-flash',
                            contents=translate_prompt
                        )
                        final_translated_text = trans_response.text
                        break
                    except Exception as e:
                        if "503" in str(e) and attempt < max_retries - 1:
                            print(f"Server Busy (503). Retrying in {retry_delay} seconds...")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            raise e

        if not final_translated_text or not final_translated_text.strip():
            return jsonify({'error': 'Translation phase failed.'}), 400
        
        doc = Document()
        doc.add_heading(f"Translation: {original_filename}", level=1)
        for paragraph in final_translated_text.split('\n'):
            if paragraph.strip():
                doc.add_paragraph(paragraph)
                
        docx_path = os.path.join(UPLOAD_FOLDER, f"{original_filename}_translated.docx")
        doc.save(docx_path)
        
        return jsonify({
            "output": [{"target": final_translated_text}],
            "download_filename": f"{original_filename}_translated.docx"
        })
        
    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/download/<filename>', methods=['GET'])
def download_file(filename):
    docx_path = os.path.join(UPLOAD_FOLDER, filename)
    return send_file(docx_path, as_attachment=True)

if __name__ == '__main__':
    app.run(port=5000)
