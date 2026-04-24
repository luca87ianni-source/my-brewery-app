import pandas as pd
import json
import os

def migra_a_json(file_excel):
    # Mappa: Tab Excel -> Nome File JSON -> Colonna da usare come Chiave
    config = {
        "Fermentabili": ("database_malti.json", "Fermentabile"),
        "Luppoli": ("database_luppoli.json", "Luppolo"),
        "Lieviti": ("database_lieviti.json", "Lievito"),
        "Stili": ("database_stili.json", "Stile"),
        "Volumi": ("database_volumi.json", "Temperatura")
    }
    
    for tab, (nome_json, chiave) in config.items():
        try:
            df = pd.read_excel(file_excel, sheet_name=tab)
            df = df.dropna(how='all') # Rimuove righe vuote
            
            # Convertiamo in dizionario: la "chiave" (es. il nome del malto) 
            # diventerà l'indice per l'accesso rapido
            dati = df.set_index(chiave).to_dict(orient='index')
            
            with open(nome_json, 'w', encoding='utf-8') as f:
                json.dump(dati, f, indent=4, ensure_ascii=False)
            print(f"✅ {tab} migrato con successo in {nome_json}")
        except Exception as e:
            print(f"❌ Errore nel tab {tab}: {e}")

if __name__ == "__main__":
    # Sostituisci con il nome esatto del tuo file
    migra_a_json("ingredienti.xlsx")