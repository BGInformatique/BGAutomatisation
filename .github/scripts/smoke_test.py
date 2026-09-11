#!/usr/bin/env python3
"""Test de fumée CI pour le binaire installer.py empaqueté.

Démarre le binaire construit par PyInstaller, attend qu'il réponde sur son
port HTTP local, vérifie /api/etat, puis l'arrête et confirme qu'il est bien
mort. Bibliothèque standard seulement, écrit en Python plutôt qu'en bash
pour rester identique sur les trois OS — tuer/attendre un processus par PID
via `kill`/`taskkill` en bash diverge trop entre MSYS (Windows) et
Linux/macOS pour être fiable ; `subprocess.Popen`/`terminate()`/`wait()`
gèrent ça correctement sur les trois grâce à Python lui-même.

Utilisé par .github/workflows/build-installer.yml — pas partie de la suite
livrée, outil de CI seulement.
"""
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = 18420


def main():
    if len(sys.argv) != 2:
        print("usage: smoke_test.py <chemin_binaire>", file=sys.stderr)
        return 1
    binaire = sys.argv[1]

    proc = subprocess.Popen([binaire, "--port", str(PORT)])
    try:
        ok = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/", timeout=2) as rep:
                    if rep.status == 200:
                        ok = True
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(1)
        if not ok:
            print("Le binaire n'a jamais répondu sur / après 30 s.", file=sys.stderr)
            return 1

        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/etat", timeout=5) as rep:
            etat = json.loads(rep.read())
        if "os_cible" not in etat or "unites" not in etat:
            print(f"/api/etat incomplet : {etat}", file=sys.stderr)
            return 1
        print(f"os_cible rapporté par le binaire : {etat['os_cible']}")
        print(f"{len(etat['unites'])} unité(s) détectée(s)")
        print("Test de fumée : OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None:
            print("ATTENTION : le processus ne s'est pas arrêté proprement.", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
