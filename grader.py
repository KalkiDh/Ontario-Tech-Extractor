import os
import sys
import glob
import time
import chromadb
import ollama
from langchain_text_splitters import RecursiveCharacterTextSplitter
from docling.document_converter import DocumentConverter

# --- CONFIGURATION ---
LLM_MODEL = "llama3.2-vision:11b"  # Your grading brain
EMBED_MODEL = "nomic-embed-text"   # Your search engine
DB_PATH = "./exam_grading_db"      # Vector DB storage folder

def clean_path(path):
    """Removes quotes and extra spaces from drag-and-dropped paths."""
    return path.strip().strip("'").strip('"')

def get_file_path(label, extension=".pdf"):
    """
    Tries to auto-detect a file. If failing, asks user to drag-and-drop.
    """
    # 1. Try Auto-Detect in current folder
    files = glob.glob(f"*{extension}")
    candidates = []
    
    if "Question" in label or "QP" in label:
        candidates = [f for f in files if "QP" in f or "Question" in f]
    elif "Marking" in label or "MS" in label:
        candidates = [f for f in files if "MS" in f or "Mark" in f]
        
    if candidates:
        print(f"   ✅ Auto-detected {label}: {candidates[0]}")
        return candidates[0]

    # 2. If fail, ask user
    print(f"\n⚠️  Could not auto-detect {label}.")
    path = input(f"   👉 Drag and drop the {label} file here and press Enter: ")
    return clean_path(path)

def extract_or_load_text(file_path):
    """
    If a .md file already exists, load it (Fast).
    If not, run Docling on the PDF (Slow, but done once).
    """
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    md_path = os.path.join(os.path.dirname(file_path), f"{base_name}.md")
    
    # OPTION A: Load existing Markdown (Time Saver)
    if os.path.exists(md_path):
        print(f"   ⚡ Found existing Markdown: {os.path.basename(md_path)}")
        with open(md_path, "r", encoding="utf-8") as f:
            return f.read()

    # OPTION B: Run Extraction
    print(f"   ⚙️  Extracting text from PDF (this takes 30s)...")
    try:
        converter = DocumentConverter()
        result = converter.convert(file_path)
        text = result.document.export_to_markdown()
        
        # Save for next time
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(text)
        return text
    except Exception as e:
        print(f"   ❌ Extraction Error: {e}")
        sys.exit(1)

def build_vector_db(qp_text, ms_text):
    """
    Chunks the text and builds the RAG database.
    """
    print("\n💾 Building Search Database...")
    
    client = chromadb.PersistentClient(path=DB_PATH)
    try:
        client.delete_collection("exam_data") # Reset DB
    except:
        pass
    collection = client.create_collection(name="exam_data")

    # Intelligent Chunking
    # chunk_size=1000 ensures we capture full questions/answers
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "Question", "\n", " "]
    )

    # 1. Index Question Paper
    qp_chunks = splitter.split_text(qp_text)
    print(f"   🔹 Indexing Question Paper ({len(qp_chunks)} chunks)...")
    for i, chunk in enumerate(qp_chunks):
        collection.add(
            ids=[f"qp_{i}"],
            documents=[chunk],
            embeddings=[ollama.embeddings(model=EMBED_MODEL, prompt=chunk)["embedding"]],
            metadatas=[{"source": "QP", "id": i}]
        )

    # 2. Index Marking Scheme
    ms_chunks = splitter.split_text(ms_text)
    print(f"   🔹 Indexing Marking Scheme ({len(ms_chunks)} chunks)...")
    for i, chunk in enumerate(ms_chunks):
        collection.add(
            ids=[f"ms_{i}"],
            documents=[chunk],
            embeddings=[ollama.embeddings(model=EMBED_MODEL, prompt=chunk)["embedding"]],
            metadatas=[{"source": "MS", "id": i}]
        )

    print("✅ Database Ready.")
    return collection

def retrieve_context(collection, query, source):
    """
    Retrieves the most relevant text from the specific document type.
    """
    response = collection.query(
        query_embeddings=[ollama.embeddings(model=EMBED_MODEL, prompt=query)["embedding"]],
        n_results=3, # Get top 3 chunks
        where={"source": source}
    )
    return "\n...\n".join(response['documents'][0])

def grade_answer_loop(collection):
    print("\n" + "="*50)
    print("🎓 AI GRADING ENGINE READY")
    print("="*50)
    
    while True:
        print("\n" + "-"*30)
        q_num = input("📝 Question Number (e.g. 'Question 3b'): ").strip()
        if q_num.lower() in ['exit', 'quit']: break
        
        student_ans = input("👤 Student Answer: ").strip()
        if not student_ans: continue
        
        print(f"\n🔍 Searching documents for '{q_num}'...", end="\r")
        
        # 1. RAG Retrieval
        qp_context = retrieve_context(collection, q_num, "QP")
        ms_context = retrieve_context(collection, q_num, "MS")
        
        # 2. The Strict Examiner Prompt
        prompt = f"""
        [ROLE]
        You are a strict, fair university examiner.
        
        [TASK]
        Grade the student's answer based STRICTLY on the Marking Scheme.
        
        [CONTEXT: QUESTION PAPER]
        {qp_context}
        
        [CONTEXT: MARKING SCHEME]
        {ms_context}
        
        [STUDENT ANSWER FOR {q_num}]
        "{student_ans}"
        
        [INSTRUCTIONS]
        1. Identify the max marks available for this question from the text.
        2. Check if the student mentioned the specific keywords required by the Marking Scheme.
        3. If the marking scheme says "Ignore X" or "Allow Y", follow that rule.
        4. Output a JSON-style summary.
        
        OUTPUT FORMAT:
        Points Awarded: X / Y
        Reasoning: [Bullet points explaining exactly why marks were given or lost]
        Feedback: [One sentence on how to improve]
        """
        
        print("🤖 Grading...                             ", end="\r")
        
        # 3. Generate Evaluation
        stream = ollama.chat(
            model=LLM_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            stream=True
        )
        
        print("\n")
        for chunk in stream:
            print(chunk['message']['content'], end="", flush=True)
        print("\n")

if __name__ == "__main__":
    print("--- 📂 FILE SETUP ---")
    
    # 1. Get Files (Auto-detect or Drag-and-Drop)
    qp_path = get_file_path("Question Paper (QP)")
    ms_path = get_file_path("Marking Scheme (MS)")
    
    # 2. Extract Text (Handles PDF or MD)
    qp_text = extract_or_load_text(qp_path)
    ms_text = extract_or_load_text(ms_path)
    
    # 3. Build RAG DB
    collection = build_vector_db(qp_text, ms_text)
    
    # 4. Start Grading
    grade_answer_loop(collection)