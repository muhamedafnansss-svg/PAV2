"""
Ollama LLM Interface
Handles communication with Ollama for LLM responses
Supports multiple models: Llama, Mistral, Qwen, Neural-Chat
"""

import logging
from typing import Optional, Iterator, List
import requests
import json

logger = logging.getLogger(__name__)


class OllamaInterface:
    """
    Interface to Ollama LLM service
    """
    
    AVAILABLE_MODELS = [
        "llama2",
        "llama2:7b",
        "llama2:13b",
        "mistral",
        "neural-chat",
        "qwen",
        "qwen:7b",
        "dolphin-mistral",
        "starling-lm",
        "vicuna",
    ]
    
    def __init__(self, api_url: str = "http://localhost:11434", model: str = "llama2"):
        self.api_url = api_url.rstrip("/")
        self.model = model
        self.is_running = False
        
        self._check_connection()
    
    def _check_connection(self) -> None:
        """Check if Ollama is running"""
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=2)
            if response.status_code == 200:
                self.is_running = True
                logger.info(f"Connected to Ollama at {self.api_url}")
                models = self.list_models()
                logger.info(f"Available models: {models}")
            else:
                logger.error(f"Ollama returned status {response.status_code}")
        except requests.exceptions.ConnectionError:
            logger.error(f"Cannot connect to Ollama at {self.api_url}")
            logger.warning("Make sure Ollama is running: ollama serve")
        except Exception as e:
            logger.error(f"Connection error: {e}")
    
    def get_response(
        self,
        messages: list,
        temperature: float = 0.7,
        top_p: float = 0.9,
        top_k: int = 40,
        num_predict: int = 500,
    ) -> Optional[str]:
        """
        Get response from LLM
        """
        if not self.is_running:
            logger.error("Ollama not running")
            return None
        
        try:
            payload = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "top_p": top_p,
                    "top_k": top_k,
                    "num_predict": num_predict,
                },
            }
            
            response = requests.post(
                f"{self.api_url}/api/chat",
                json=payload,
                timeout=60,
            )
            
            if response.status_code == 200:
                result = response.json()
                return result.get("message", {}).get("content", "")
            else:
                logger.error(f"Ollama error: {response.status_code}")
                return None
        except requests.exceptions.Timeout:
            logger.error("Ollama request timed out")
            return None
        except Exception as e:
            logger.error(f"Error getting response: {e}")
            return None
    
    def list_models(self) -> list:
        """
        List available models
        """
        if not self.is_running:
            return []
        
        try:
            response = requests.get(f"{self.api_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception as e:
            logger.error(f"Error listing models: {e}")
        
        return []
    
    def set_model(self, model_name: str) -> None:
        """Switch to different model"""
        self.model = model_name
        logger.info(f"Model set to {model_name}")
    
    def pull_model(self, model_name: str) -> bool:
        """
        Download a model from Ollama library
        """
        if not self.is_running:
            logger.error("Ollama not running")
            return False
        
        try:
            logger.info(f"Pulling model: {model_name}")
            payload = {"name": model_name}
            response = requests.post(
                f"{self.api_url}/api/pull",
                json=payload,
                timeout=600,
            )
            
            if response.status_code == 200:
                logger.info(f"Model {model_name} pulled successfully")
                return True
            else:
                logger.error(f"Pull failed: {response.status_code}")
                return False
        except Exception as e:
            logger.error(f"Error pulling model: {e}")
            return False
