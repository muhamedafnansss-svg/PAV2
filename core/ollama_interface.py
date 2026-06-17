import logging
from typing import Optional, List
import requests
import json

logger = logging.getLogger(__name__)

class OllamaInterface:
    AVAILABLE_MODELS = ["llama2", "llama2:7b", "llama2:13b", "mistral", "neural-chat", "qwen", "qwen:7b", "dolphin-mistral", "starling-lm", "vicuna"]
    
    def __init__(self, api_url: str = "http://localhost:11434", model: str = "llama2"):
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.is_running = False
        self._check_connection()
    
    def _check_connection(self) -> None:
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=2)
            if response.status_code == 200:
                self.is_running = True
                logger.info(f"Connected to Ollama at {self.api_url}")
                models = self.list_models()
                logger.info(f"Available models: {models}")
        except:
            logger.error(f"Cannot connect to Ollama at {self.api_url}")
            logger.warning("Make sure Ollama is running: ollama serve")
    
    def get_response(self, messages: list, temperature: float = 0.7, top_p: float = 0.9, top_k: int = 40, num_predict: int = 500) -> Optional[str]:
        if not self.is_running:
            return None
        
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "top_p": top_p, "top_k": top_k, "num_predict": num_predict},
            }
            response = requests.post(f"{self.api_url}/api/chat", json=payload, timeout=60)
            if response.status_code == 200:
                return response.json().get("message", {}).get("content", "")
        except Exception as e:
            logger.error(f"Error: {e}")
        return None
    
    def list_models(self) -> list:
        if not self.is_running:
            return []
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=5)
            if response.status_code == 200:
                return [m["name"] for m in response.json().get("models", [])]
        except:
            pass
        return []
    
    def set_model(self, model_name: str) -> None:
        self.model = model_name
        logger.info(f"Model set to {model_name}")
    
    def pull_model(self, model_name: str) -> bool:
        if not self.is_running:
            return False
        try:
            logger.info(f"Pulling model: {model_name}")
            response = requests.post(f"{self.api_url}/api/pull", json={"name": model_name}, timeout=600)
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Error: {e}")
            return False
