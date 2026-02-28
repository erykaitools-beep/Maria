import time
import os
import datetime
import sys

# Import z interpreter.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from maria_core.agent.interpreter import (
    ensure_dirs, MEMORY_DIR, LINKS_DIR, LOGS_DIR, STATE_DIR,
    handle_MEM, handle_REFLECT, handle_THINK, handle_QUERY, log_line
)
from maria_core.perception.perception import read_input_queue
from maria_core.utils.actions import perform_action

# Lokalny mózg Marii przez Ollamę
from models.ollama_brain import OllamaBrain

# NOWE: pamięć semantyczna + pętla mózgu/pamięci
from maria_core.memory.semantic.semantic_graph import SemanticGraph
from maria_core.memory_engine.brain_memory_integration import BrainMemoryLoop


class AIAgent:
    def __init__(self, name="Maria"):
        """Inicjalizuj agenta"""
        ensure_dirs()
        self.name = name
        self.running = True
        self.cycle_count = 0
        self.perception_count = 0

        # Lokalne LLM (mózg M.A.R.I.A. przez Ollamę – Llama 3.1 8B)
        self.brain = OllamaBrain(
            model="llama3.1:8b",
            verify_model=False,  # wyłączamy weryfikację listy modeli, żeby nie hałasowało
            log_fn=log_line      # NOWE: logowanie z poziomu mózgu (opcjonalne, ale przydatne)
        )

        # NOWE: pamięć semantyczna (graf) + pamięć epizodyczna + pętla mózg–pamięć
        self.semantic_memory = SemanticGraph()
        self.episodic_memory = []  # lista epizodów z BrainMemoryLoop

        self.brain_memory_loop = BrainMemoryLoop(
            semantic_memory=self.semantic_memory,
            episodic_memory=self.episodic_memory,
            maria_brain=self.brain,   # ta sama instancja LLM co wyżej
            log_fn=log_line,
            chunk_size=1500,          # próg dzielenia dużych tekstów
        )
        
        log_line(f"=== AGENT {self.name} INITIALIZED ===")
        self.update_state(state="initialized")
    
    def should_reflect(self):
        """Czy agent powinien wykonać REFLECT?"""
        # Co 10 cykli
        return self.cycle_count % 10 == 0
    
    def should_think(self):
        """Czy agent powinien wykonać THINK?"""
        # Co 20 cykli
        return self.cycle_count % 20 == 0
    
    def should_query_memory(self):
        """Czy agent powinien przeszukać swoją pamięć?"""
        # Co 15 cykli
        return self.cycle_count % 15 == 0
    
    def perceive(self):
        """Agent odbiera informacje ze świata"""
        try:
            perceptions = read_input_queue()
            
            if perceptions:
                log_line(f"[Percepcja] Agent odebrał {len(perceptions)} nowych informacji")
                self.perception_count += len(perceptions)
                
                for p in perceptions:
                    # Automatycznie zapisz jako pamięć
                    content = p['content']
                    source = p['source']
                    
                    log_line(f"[Percepcja] Przetwarzam dane ze źródła: {source}")
                    
                    # Wywołaj handle_MEM
                    handle_MEM([
                        "MEM",
                        content,
                        f"Odebrane z {source} o {p['timestamp'].strftime('%H:%M')}",
                        "percepcja,input,external",
                        "auto"
                    ])
                    
                    # Wykonaj akcję - powiadom o nowej percepcji
                    perform_action("log", {
                        "message": f"Nowa percepcja zarejestrowana: {source}"
                    })
            
            return perceptions
            
        except Exception as e:
            log_line(f"[ERROR] Percepcja nie powiodła się: {str(e)}")
            return []

    # NOWE: pipeline mózg + pamięć nad każdą percepcją
    def process_perceptions_with_memory(self, perceptions):
        """
        Przepuszcza percepcje przez BrainMemoryLoop:
        - dzieli duże teksty na chunki
        - wyciąga fakty (memory_facts) i zapisuje do grafu
        - przywołuje powiązane wspomnienia z grafu
        - generuje rozumowanie z kontekstem pamięci
        Zwraca listę wyników (po jednym dict na percepcję).
        """
        results = []
        if not perceptions:
            return results

        for p in perceptions:
            try:
                content = p.get("content", "")
                source = p.get("source", "unknown")

                log_line(f"[BrainMemory] Przetwarzam percepcję z {source} (len={len(content)})")
                res = self.brain_memory_loop.process_perception(
                    content,
                    context=f"source={source}"
                )
                results.append(res)

                log_line(
                    f"[BrainMemory] Zakończono. "
                    f"Chunks={res.get('chunks_processed', 1)}, "
                    f"facts={res.get('total_facts_added', 0)}"
                )
            except Exception as e:
                log_line(f"[ERROR] BrainMemoryLoop dla percepcji z {p.get('source','?')} nie powiódł się: {str(e)}")

        log_line(f"[BrainMemory] Pipeline zakończony dla {len(results)} percepcji")
        return results
    
    def process_memory(self):
        """Agent przetwarza swoją pamięć"""
        try:
            log_line(f"[Cykl {self.cycle_count}] Agent przetwarza pamięć...")
            
            # QUERY - co 15 cykli
            if self.should_query_memory():
                log_line("[Pamięć] Wykonuję QUERY na kluczowych tagach...")
                # Przeszukaj pamięć po tagu "percepcja"
                try:
                    handle_QUERY(["QUERY", "tag", "percepcja", "", ""])
                except:
                    pass
            
            # REFLECT - co 10 cykli
            if self.should_reflect():
                log_line("[Pamięć] Wykonuję REFLECT - analizuję ostatnie wspomnienia...")
                try:
                    handle_REFLECT(["REFLECT", "5"])
                    perform_action("log", {"message": "REFLECT zakończony - nowe insights wygenerowane"})
                except Exception as e:
                    log_line(f"[ERROR] REFLECT nie powiódł się: {str(e)}")
            
            # THINK - co 20 cykli
            if self.should_think():
                log_line("[Pamięć] Wykonuję THINK - wnioskuję nowe fakty...")
                try:
                    # Znajdź ostatnie 3 pamięci
                    mem_files = sorted([
                        f for f in os.listdir(MEMORY_DIR) 
                        if f.endswith(".txt")
                    ])
                    
                    if len(mem_files) >= 3:
                        last_three = [f.split(".")[0] for f in mem_files[-3:]]
                        mem_ids = ",".join(last_three)
                        log_line(f"[THINK] Analizuję pamięci: {mem_ids}")
                        
                        handle_THINK([
                            "THINK",
                            mem_ids,
                            "Co łączy te wspomnienia? Jaki jest wspólny wzór?"
                        ])
                        
                        perform_action("log", {"message": f"THINK zakończony na {len(last_three)} wspomnieniach"})
                except Exception as e:
                    log_line(f"[ERROR] THINK nie powiódł się: {str(e)}")
        
        except Exception as e:
            log_line(f"[ERROR] Przetwarzanie pamięci nie powiodło się: {str(e)}")

    def think_with_brain(self, perceptions):
        """
        Maria (LLM) analizuje percepcje z tego cyklu i daje podsumowanie / sugestię kroku.
        """
        try:
            if not perceptions:
                return  # brak nowych danych - nie ma nad czym myśleć

            # Zbuduj prosty kontekst tekstowy z percepcji
            lines = []
            for p in perceptions:
                ts = p["timestamp"].strftime("%Y-%m-%d %H:%M")
                src = p["source"]
                content = p["content"]
                lines.append(f"- {ts} [{src}] {content}")
            context_text = "\n".join(lines)

            prompt = (
                "Kontekst z ostatniego cyklu percepcji:\n"
                f"{context_text}\n\n"
                "Podsumuj to w jednym–dwóch zdaniach po polsku i, jeśli to ma sens, "
                "zaproponuj kolejny logiczny krok dla agenta M.A.R.I.A."
            )

            reply = self.brain.think(prompt, temperature=0.2)
            log_line(f"[LLM] Podsumowanie Marii: {reply}")
            perform_action("log", {"message": f"Maria (LLM): {reply}"})

        except Exception as e:
            log_line(f"[ERROR] think_with_brain nie powiodło się: {str(e)}")
    
    def update_state(self, state="active", context=""):
        """Agent aktualizuje swój stan"""
        try:
            state_file = os.path.join(STATE_DIR, "current.txt")
            now = datetime.datetime.now()
            
            with open(state_file, "w", encoding="utf-8") as f:
                f.write(f"agent: {self.name}\n")
                f.write(f"czas: {now.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"cykl: {self.cycle_count}\n")
                f.write(f"percepcje: {self.perception_count}\n")
                f.write(f"stan: '{state}'\n")
                if context:
                    f.write(f"kontekst: {context}\n")
        
        except Exception as e:
            log_line(f"[ERROR] Aktualizacja stanu nie powiodła się: {str(e)}")
    
    def run_cycle(self):
        """Jeden cykl życia agenta"""
        self.cycle_count += 1
        
        try:
            # 1. Odbierz informacje
            perceptions = self.perceive()

            # 1.5. NOWE: przepuść percepcje przez pętlę mózg–pamięć (graf + epizody)
            if perceptions:
                self.process_perceptions_with_memory(perceptions)
            
            # 2. Przetwórz pamięć (REFLECT/THINK/QUERY na plikach)
            self.process_memory()

            # 3. Maria (LLM) analizuje percepcje z tego cyklu (krótkie podsumowanie)
            self.think_with_brain(perceptions)
            
            # 4. Zaktualizuj stan
            context = f"cycle_{self.cycle_count}, perceptions_{len(perceptions)}"
            self.update_state(state="active", context=context)
            
            log_line(f"[✓] Cykl {self.cycle_count} zakończony\n")
            
        except Exception as e:
            log_line(f"[ERROR] Cykl {self.cycle_count} nie powiódł się: {str(e)}")
            self.update_state(state="error", context=str(e))
    
    def run(self, cycles=None, interval=5):
        """Główna pętla agenta"""
        try:
            log_line(f"\n{'='*60}")
            log_line(f"=== AGENT {self.name.upper()} URUCHOMIONY ===")
            log_line(f"Czas: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            log_line(f"{'='*60}\n")
            
            self.update_state(state="running")
            
            if cycles is None:
                # Infinite loop
                print(f"[{self.name}] Agent pracuje w trybie nieskończonym (Ctrl+C by zatrzymać)")
                cycle = 0
                while self.running:
                    try:
                        self.run_cycle()
                        time.sleep(interval)
                        cycle += 1
                    except KeyboardInterrupt:
                        print(f"\n[{self.name}] Otrzymano sygnał przerwania...")
                        break
                    except Exception as e:
                        log_line(f"[ERROR] Nieoczekiwany błąd w pętli: {str(e)}")
                        time.sleep(interval)
            else:
                # Fixed number of cycles
                print(f"[{self.name}] Agent pracuje w trybie testowym ({cycles} cykli)")
                for _ in range(cycles):
                    self.run_cycle()
                    time.sleep(interval)
            
            self.update_state(state="stopped")
            log_line(f"\n{'='*60}")
            log_line(f"=== AGENT {self.name.upper()} ZATRZYMANY ===")
            log_line(f"Razem cykli: {self.cycle_count}")
            log_line(f"Razem percepcji: {self.perception_count}")
            log_line(f"{'='*60}\n")
        
        except Exception as e:
            log_line(f"[FATAL ERROR] Agent crash: {str(e)}")
            self.update_state(state="crashed", context=str(e))


if __name__ == "__main__":
    # Test: uruchom 10 cykli co 1 minutę (60 sekund)
    agent = AIAgent(name="Maria")
    agent.run(cycles=10, interval=60)
    
    # Tryb produkcyjny (nieskończony loop):
    # agent.run(interval=60)
