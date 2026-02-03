import os
import glob
import json
import ollama

# --- CONFIGURATION ---
# The 34B Heavyweight (Uses ~20GB RAM)
MODEL_NAME = "llama3.2-vision:11b"

def load_file(path):
    if not os.path.exists(path):
        print(f"❌ Error: File not found at {path}")
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def extract_images_from_folder(md_path):
    # (Same logic as before to find the _media folder)
    base_name = os.path.splitext(os.path.basename(md_path))[0]
    clean_name = base_name.replace("_MAPPED", "").replace("_extracted", "").replace("_FULL", "")
    script_dir = os.path.dirname(os.path.abspath(md_path))
    media_dir = os.path.join(script_dir, f"{clean_name}_media")
    
    if os.path.exists(media_dir):
        images = sorted(glob.glob(os.path.join(media_dir, "*.png")))
        print(f"   🖼️  Attached {len(images)} images.")
        return images
    else:
        print(f"   ⚠️ No images found at {media_dir}")
        return []

def grade_student_heavy(question_paper_path, marking_scheme_path, student_answer_text):
    print(f"🚀 Initializing Heavy Grading with {MODEL_NAME}...")
    print("   ⚠️  WARNING: This model is huge (34B). Your Mac might freeze slightly.")

    # 1. Load Texts
    qp_text = load_file(question_paper_path)
    ms_text = load_file(marking_scheme_path)
    
    if not qp_text or not ms_text:
        return

    # 2. Images
    qp_images = extract_images_from_folder(question_paper_path)

    # 3. Prompt (Kept slightly shorter to save RAM)
    prompt = f"""
    Role: University Examiner.
    Task: Grade the Student Answer using the Marking Scheme.
    
    [QUESTION PAPER]
    {qp_text[:4000]} ... (Truncated to fit 34B context)
    
    [MARKING SCHEME]
    {ms_text}
    
    [STUDENT ANSWER]
    "{student_answer_text}"
    
    Instructions:
    1. Use provided images if needed.
    2. Output strict JSON only.
    
    {{
        "score_awarded": 0,
        "max_marks": 5,
        "reasoning": "...",
        "feedback": "..."
    }}
    """

    print("   🤖 Sending to Llava 34B (Expect 1-3 mins wait)...")

    try:
        response = ollama.chat(
            model=MODEL_NAME,
            messages=[{
                'role': 'user',
                'content': prompt,
                'images': qp_images
            }]
        )

        print("\n" + "="*50)
        print("🎓 HEAVY GRADING RESULT")
        print("="*50)
        print(response['message']['content'])

    except Exception as e:
        print(f"❌ Grading Failed: {e}")

if __name__ == "__main__":
    # Test Data
    qp_file = "Computer Systems QP_MAPPED.md" 
    ms_file = "Biology A (Biological Diversity) MS_FULL.md" 
    
    student_answer = """
    Question 3b:
    1. Lawfulness, fairness and transparency.
    2. Purpose limitation.
    3. Data minimization.
    """

    grade_student_heavy(qp_file, ms_file, student_answer)