# MariaAgent.py
# Interaktywny REPL do Twojej Marii (bez blokującego agent_loop)

import maria_core.agent.interpreter  # korzystamy z istniejących funkcji

def process_command(line: str):
    """
    Przetwarza pojedynczą linię komendy w tym samym stylu,
    co interpreter.run_script (MEM, STATE, THINK, REFLECT itd.).
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return

    parts = line.split("|")
    cmd = parts[0].strip().upper()

    if cmd == "MEM":
        interpreter.handle_MEM(parts)
    elif cmd == "STATE":
        interpreter.handle_STATE(parts)
    elif cmd == "LINK":
        interpreter.handle_LINK(parts)
    elif cmd == "DEFINE":
        interpreter.handle_DEFINE(parts)
    elif cmd == "QUERY":
        interpreter.handle_QUERY(parts)
    elif cmd == "THINK":
        interpreter.handle_THINK(parts)
    elif cmd == "REFLECT":
        interpreter.handle_REFLECT(parts)
    elif cmd == "ASSOCIATE":
        interpreter.handle_ASSOCIATE(parts)
    elif cmd == "GOAL":
        interpreter.handle_GOAL(parts)
    elif cmd == "EVAL_GOAL":
        interpreter.handle_EVAL_GOAL(parts)
    elif cmd in ("EXIT", "QUIT", "Q"):
        # specjalny przypadek – wyjście z REPL
        raise SystemExit
    else:
        print(f"❓ Nieznana komenda: {line}")


def main():
    # upewnij się, że katalogi memory/, logs/ itd. istnieją
    interpreter.ensure_dirs()

    print("══════════════════════════════════════")
    print("   MARIA – TRYB INTERAKTYWNY (REPL)")
    print("══════════════════════════════════════")
    print("Przykłady:")
    print("  MEM|To jest test pamięci|ręczny test|test,manual|5")
    print("  QUERY|text|test|10")
    print("  THINK|001,002|wniosek z dwóch pamięci")
    print("  REFLECT|5|auto refleksja")
    print("  ASSOCIATE|")
    print("  GOAL|Startup|Opis mojego startupu|7")
    print("  EVAL_GOAL|Startup|w_toku|idzie do przodu")
    print("  EXIT  – wyjście z sesji")
    print("══════════════════════════════════════\n")

    while True:
        try:
            line = input("Maria> ")
        except (EOFError, KeyboardInterrupt):
            print("\n👋 Koniec sesji.")
            break

        line = line.strip()
        if not line:
            continue

        try:
            process_command(line)
        except SystemExit:
            print("👋 EXIT – zamykam REPL Marii.")
            break
        except Exception as e:
            print(f"❌ Błąd podczas przetwarzania komendy: {e}")


if __name__ == "__main__":
    main()
