import subprocess 
import os from datetime 
import datetime 

def maria_write_code(filename: str, code: str):
    path = os.path.join("maria_generated", filename)

 os.makedirs("maria_generated", exist_ok=True)
 with open(path, "w", encoding="utf-8") as f: 
    f.write(code)
 print(f"[MARIA CODE] Napisałam: {path}") return path
def maria_run_code(path: str): 
try: result = subprocess.run( 
["python", path], 
capture_output=True, 
text=True, 
timeout=30 )
if result.returncode == 0: 
print(f"[MARIA RUN] Sukces: {result.stdout}") 
return "SUCCESS", result.stdout 
else: 
print(f"[MARIA RUN] Błąd: {result.stderr}") 
return "ERROR", result.stderr 
except Exception as e: 
return "CRASH", str(e)