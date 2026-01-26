import os
import datetime
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

def ensure_output_dir():
    """Stwórz folder output jeśli nie istnieje"""
    if not os.path.isdir(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

def perform_action(action_type, params):
    """
    Agent wykonuje akcje w świecie
    
    Typy akcji:
    - "log": zapisz log
    - "ask_user": zadaj pytanie użytkownikowi
    - "create_hypothesis": stwórz hipotezę
    - "generate_insight": wygeneruj wniosek
    - "alert": wyślij alert
    """
    
    ensure_output_dir()
    
    if action_type == "log":
        message = params.get("message", "")
        print(f"[Akcja] LOG: {message}")
        _log_action("log", message)
    
    elif action_type == "ask_user":
        question = params.get("question", "")
        category = params.get("category", "general")
        
        print(f"\n[Akcja] PYTANIE do użytkownika ({category}):")
        print(f"  {question}\n")
        
        _write_to_output("questions", f"[{category}] {question}")
    
    elif action_type == "create_hypothesis":
        hypothesis = params.get("hypothesis", "")
        confidence = params.get("confidence", 0.5)
        tags = params.get("tags", "hypothesis")
        
        print(f"[Akcja] HIPOTEZA (ufność: {confidence}):")
        print(f"  {hypothesis}\n")
        
        _write_to_output("hypotheses", f"[{confidence}] {hypothesis} (#{tags})")
    
    elif action_type == "generate_insight":
        insight = params.get("insight", "")
        source = params.get("source", "unknown")
        
        print(f"[Akcja] WNIOSEK (ze źródła: {source}):")
        print(f"  {insight}\n")
        
        _write_to_output("insights", f"[z: {source}] {insight}")
    
    elif action_type == "alert":
        level = params.get("level", "info")  # info, warning, critical
        message = params.get("message", "")
        
        print(f"[Akcja] ALERT ({level}):")
        print(f"  {message}\n")
        
        _write_to_output("alerts", f"[{level.upper()}] {message}")
    
    else:
        print(f"[Akcja] UNKNOWN ACTION TYPE: {action_type}")

def _log_action(action_type, content):
    """Wewnętrzna funkcja do logowania akcji"""
    try:
        log_file = os.path.join(OUTPUT_DIR, "actions.log")
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {action_type}: {content}\n")
    except Exception as e:
        print(f"[ERROR] Nie mogę zapisać do actions.log: {str(e)}")

def _write_to_output(output_type, content):
    """Zapisz wyjście agenta do odpowiedniego pliku"""
    try:
        ensure_output_dir()
        
        # Określ plik na podstawie typu
        file_mapping = {
            "questions": "ai_questions.txt",
            "hypotheses": "ai_hypotheses.txt",
            "insights": "ai_insights.txt",
            "alerts": "ai_alerts.txt"
        }
        
        filename = file_mapping.get(output_type, "ai_output.txt")
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"[{now}] {content}\n")
    
    except Exception as e:
        print(f"[ERROR] Nie mogę zapisać do {output_type}: {str(e)}")

def get_recent_actions(output_type="all", limit=10):
    """Przeczytaj ostatnie akcje"""
    ensure_output_dir()
    
    if output_type == "all":
        files = [
            "ai_questions.txt",
            "ai_hypotheses.txt",
            "ai_insights.txt",
            "ai_alerts.txt"
        ]
    else:
        file_mapping = {
            "questions": "ai_questions.txt",
            "hypotheses": "ai_hypotheses.txt",
            "insights": "ai_insights.txt",
            "alerts": "ai_alerts.txt"
        }
        files = [file_mapping.get(output_type, "ai_output.txt")]
    
    print(f"\n[Akcje] Ostatnie działania ({output_type}):\n")
    
    for filename in files:
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        if not os.path.exists(filepath):
            continue
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
            
            print(f"--- {filename} ---")
            for line in lines:
                print(line.rstrip())
            print()
        
        except Exception as e:
            print(f"[ERROR] Nie mogę przeczytać {filename}: {str(e)}")

def clear_output():
    """Wyczyść foldery output (ostrożnie!)"""
    ensure_output_dir()
    
    file_mapping = {
        "questions": "ai_questions.txt",
        "hypotheses": "ai_hypotheses.txt",
        "insights": "ai_insights.txt",
        "alerts": "ai_alerts.txt",
        "log": "actions.log"
    }
    
    for key, filename in file_mapping.items():
        filepath = os.path.join(OUTPUT_DIR, filename)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                print(f"[Akcje] Wyczyszczono: {filename}")
            except Exception as e:
                print(f"[ERROR] Nie mogę wyczyścić {filename}: {str(e)}")

if __name__ == "__main__":
    # Test akcji
    perform_action("log", {"message": "System testowy uruchomiony"})
    
    perform_action("ask_user", {
        "question": "Jakie są twoje główne cele dla systemu AI?",
        "category": "strategy"
    })
    
    perform_action("create_hypothesis", {
        "hypothesis": "AI z pamięcią może być bardziej efektywna w podejmowaniu decyzji",
        "confidence": 0.75,
        "tags": "ai,memory,hypothesis"
    })
    
    perform_action("generate_insight", {
        "insight": "Percepcja i refleksja to kluczowe komponenty autonomicznego agenta",
        "source": "agent_analysis"
    })
    
    perform_action("alert", {
        "level": "info",
        "message": "Agent iniciuje cykl analizy"
    })
    
    print("\n--- Ostatnie akcje ---")
    get_recent_actions()
