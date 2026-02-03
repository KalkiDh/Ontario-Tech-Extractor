import os
import sys
import ollama
import chromadb
from langchain_text_splitters import RecursiveCharacterTextSplitter

# --- CONFIGURATION ---
LLM_MODEL = "llama3.2-vision:11b"     # Your chat model
EMBED_MODEL = "nomic-embed-text"      # Your search model
DB_PATH = "./exam_vector_db"          # Where to save the database

def get_embedding(text):
    """
    Generates a vector embedding for a chunk of text using Ollama.
    """
    try:
        response = ollama.embeddings(model=EMBED_MODEL, prompt=text)
        return response["embedding"]
    except Exception as e:
        print(f"❌ Embedding Error: {e}")
        return []

def ingest_file(file_path):
    """
    1. Reads the Markdown
    2. Chunks it intelligently
    3. Stores it in Vector DB
    """
    print(f"\n📂 Loading: {os.path.basename(file_path)}...")
    
    if not os.path.exists(file_path):
        print("❌ File not found.")
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        text = f.read()

    # --- INTELLIGENT CHUNKING ---
    # We use RecursiveCharacterTextSplitter.
    # It tries to split on paragraphs (\n\n) first, then lines (\n), then spaces.
    # Chunk Size 1000: Large enough to hold a full exam question.
    # Overlap 200: Ensures context isn't lost if a question is cut in the middle.
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200,
        separators=["\n\n", "\n", " ", ""]
    )
    
    chunks = splitter.split_text(text)
    print(f"🧩 Split into {len(chunks)} chunks.")

    # --- VECTOR DATABASE ---
    print("💾 Building Vector Database (this may take a moment)...")
    client = chromadb.PersistentClient(path=DB_PATH)
    
    # Create or reset collection
    collection_name = "exam_paper"
    try:
        client.delete_collection(collection_name)
    except:
        pass
    collection = client.create_collection(name=collection_name)

    # Embed and Add Chunks
    # We batch them to be polite to the CPU
    for i, chunk in enumerate(chunks):
        print(f"   🔹 Embedding chunk {i+1}/{len(chunks)}...", end="\r")
        vector = get_embedding(chunk)
        
        if vector:
            collection.add(
                ids=[f"chunk_{i}"],
                documents=[chunk],
                embeddings=[vector],
                metadatas=[{"source": file_path, "chunk_id": i}]
            )
    
    print(f"\n✅ Database Ready! Stored in '{DB_PATH}'")
    return collection

def retrieve_context(collection, query, n_results=5):
    """
    Semantic Search: Finds the 5 most relevant chunks for your question.
    """
    query_vec = get_embedding(query)
    results = collection.query(
        query_embeddings=[query_vec],
        n_results=n_results
    )
    return results['documents'][0]

def chat_loop(collection):
    print("\n" + "="*50)
    print("💬 EXAM CHATBOT READY")
    print("   (Type 'exit' to quit)")
    print("="*50)

    conversation_history = []

    while True:
        user_input = input("\n❓ You: ").strip()
        if user_input.lower() in ["exit", "quit"]:
            break
        if not user_input:
            continue

        # 1. Retrieve
        print("   🔍 Searching docs...", end="\r")
        retrieved_chunks = retrieve_context(collection, user_input)
        context_block = "\n\n---\n\n".join(retrieved_chunks)

        # 2. Prompt
        prompt = f"""
                You are a helpful Retrieval Assistant. 
                1. Answer strictly based on the [CONTEXT] provided.
                2. If the user asks a math/logic question, DO NOT SOLVE IT. Instead, quote the relevant numbers or question text.
                3. If you cannot find the answer in the context, say "I don't know".

                [CONTEXT]
                {context_block}

                [USER QUESTION]
                {user_input}
                """

        # 3. Generate
        print("   🤖 Thinking...", end="\r")
        stream = ollama.chat(
            model=LLM_MODEL,
            messages=[{'role': 'user', 'content': prompt}],
            stream=True
        )

        print("\r💡 Assistant: ", end="")
        full_response = ""
        for chunk in stream:
            content = chunk['message']['content']
            print(content, end="", flush=True)
            full_response += content
        print("\n")

if __name__ == "__main__":
    # --- STEP 1: LOAD DATA ---
    # Path to your MAPPED markdown file
    target_file = "Computer Systems QP_FULL.md" 

    # Initialize DB
    if not os.path.exists(target_file):
        # Allow running without file if DB exists, otherwise error
        if os.path.exists(DB_PATH):
             client = chromadb.PersistentClient(path=DB_PATH)
             collection = client.get_collection("exam_paper")
        else:
             print(f"Please check the file path in the script: {target_file}")
             sys.exit()
    else:
        # Re-ingest (Optional: you can comment this out to skip re-indexing every time)
        collection = ingest_file(target_file)

    # --- STEP 2: CHAT ---
    chat_loop(collection)