import tkinter as tk
from tkinter import ttk
import requests
import json

class OllamaBot:
    def __init__(self, root):
        self.root = root
        self.root.title("Ollama Model Selector")
        self.root.geometry("400x300")
        
        self.label = ttk.Label(root, text="Select a Model to Load:")
        self.label.pack(pady=10)
        
        self.model_var = tk.StringVar()
        self.model_dropdown = ttk.Combobox(root, textvariable=self.model_var, state="readonly")
        self.model_dropdown.pack(pady=10, padx=20, fill=tk.X)
        
        self.load_button = ttk.Button(root, text="Load Model", command=self.load_model)
        self.load_button.pack(pady=10)
        
        self.status_label = ttk.Label(root, text="Status: Waiting for selection...")
        self.status_label.pack(pady=10)
        
        self.load_models()
    
    def load_models(self):
        try:
            response = requests.get("http://localhost:11434/api/tags")
            if response.status_code == 200:
                models_data = response.json()
                models = [model['name'] for model in models_data.get('models', [])]
                if models:
                    self.model_dropdown['values'] = models
                    self.model_var.set(models[0])
                    self.status_label.config(text="Status: Models loaded successfully")
                else:
                    self.status_label.config(text="Status: No models found")
            else:
                self.status_label.config(text=f"Status: Error {response.status_code}")
        except Exception as e:
            self.status_label.config(text=f"Status: Connection failed - {str(e)}")
    
    def load_model(self):
        selected_model = self.model_var.get()
        if selected_model:
            self.status_label.config(text=f"Status: Loading {selected_model}...")
            try:
                response = requests.post("http://localhost:11434/api/pull", 
                                        json={'name': selected_model}, 
                                        stream=False)
                if response.status_code == 200:
                    self.status_label.config(text=f"Status: {selected_model} loaded successfully")
                else:
                    self.status_label.config(text=f"Status: Failed to load {selected_model}")
            except Exception as e:
                self.status_label.config(text=f"Status: Error loading model - {str(e)}")
        else:
            self.status_label.config(text="Status: No model selected")

if __name__ == "__main__":
    root = tk.Tk()
    app = OllamaBot(root)
    root.mainloop()