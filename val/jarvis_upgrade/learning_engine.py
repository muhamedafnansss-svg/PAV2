import os
import json
import hashlib

class LearningEngine:
    """
    Manages document indexing and educational workflows.
    Helps the user study AI/ML by digesting local texts and generating quizzes.
    """
    
    def __init__(self, data_dir="jarvis_knowledge"):
        self.data_dir = data_dir
        self.index_file = os.path.join(self.data_dir, "index.json")
        
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            
        if not os.path.exists(self.index_file):
            with open(self.index_file, "w") as f:
                json.dump({}, f)

    def _load_index(self):
        with open(self.index_file, "r") as f:
            return json.load(f)
            
    def _save_index(self, index_data):
        with open(self.index_file, "w") as f:
            json.dump(index_data, f, indent=4)

    def ingest_document(self, filepath):
        """
        Reads a local text file and adds it to the learning database.
        In a full implementation, this would chunk the text and send it to a vector DB (like Chroma or FAISS).
        """
        if not os.path.exists(filepath):
            return f"Error: File {filepath} not found."
            
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                
            doc_id = hashlib.md5(filepath.encode()).hexdigest()
            
            # Simple indexing for demonstration
            index = self._load_index()
            index[doc_id] = {
                "filepath": filepath,
                "length": len(content),
                "preview": content[:100] + "..."
            }
            self._save_index(index)
            
            return f"Successfully ingested document: {filepath} ({len(content)} characters)"
            
        except Exception as e:
            return f"Error reading document: {str(e)}"

    def generate_daily_quiz(self, topic="AI/ML"):
        """
        Generates a placeholder prompt to be sent to the LLM to create a quiz.
        The main orchestrator will pass this prompt to the active model.
        """
        prompt = f"""
        You are Jarvis, an expert AI tutor. 
        Based on our recent studies in {topic}, please generate a 3-question multiple-choice quiz.
        Include the correct answers and a brief explanation at the end.
        """
        return prompt

    def summarize_topic(self, topic):
        """
        Generates a placeholder prompt to ask the LLM for a daily summary.
        """
        prompt = f"""
        You are Jarvis. Please provide a concise, 3-paragraph summary explaining the core concepts of {topic}. 
        Assume I am a beginner but want technical accuracy.
        """
        return prompt

# Example usage
if __name__ == "__main__":
    le = LearningEngine()
    print("Quiz Prompt Generated:")
    print(le.generate_daily_quiz("Neural Networks"))
