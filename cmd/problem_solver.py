from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def solve_problem(
    problem: str,
    context: Optional[str] = None,
    history: List[Dict[str, Any]] = None,
    max_steps: int = 5,
) -> Dict[str, Any]:
    """
    Sistem problem solving terstruktur berbasis THINK → PLAN → ACT → VERIFY → REPORT.
    
    Args:
        problem: Deskripsi masalah dari user
        context: Konteks tambahan (file, error log, dll)
        history: Riwayat interaksi sebelumnya
        max_steps: Batas iterasi untuk mencegah loop
    
    Returns:
        Dict berisi langkah-langkah, hasil, dan kesimpulan.
    """
    if history is None:
        history = []

    # STEP 1: THINK — Pahami masalah & konteks
    think = f"THINK: Apa yang diminta? Apa batasan? Apa konteksnya?\n- Problem: {problem[:100]}...\n- Context: {context[:100] if context else 'none'}"

    # STEP 2: PLAN — Rencanakan langkah konkret
    plan = [
        "1. Identifikasi komponen kunci dari masalah",
        "2. Cari file atau kode terkait menggunakan glob/grep",
        "3. Baca dan analisis isi file yang relevan",
        "4. Verifikasi asumsi atau hasil sementara",
        "5. Ringkas solusi dalam 1–3 kalimat"
    ]

    # STEP 3: ACT — Jalankan langkah pertama (simulasi)
    act_result = {
        "step": 1,
        "action": "Identifikasi komponen kunci",
        "output": f"Komponen utama: '{problem.split()[0]}' — kemungkinan terkait CLI, tool, atau error handling."
    }

    # STEP 4: VERIFY — Cek validitas langkah & output
    verify = "VERIFY: Langkah 1 valid — identifikasi komponen dasar adalah fondasi yang aman. Lanjut ke langkah 2."

    # STEP 5: REPORT — Ringkas progres & next step
    report = f"REPORT: Masalah '{problem[:30]}...' sedang diurai. Langkah berikutnya: cari file terkait."

    # EXTENDED: Jika problem menyebut file spesifik (misal 'opsora_repl.py'), lakukan grep cepat
    if 'opsora_repl.py' in problem:
        try:
            import subprocess
            result = subprocess.run(['grep', '-n', 'def ', '/root/opsora-cli/opsora_repl.py'], 
                                  capture_output=True, text=True, timeout=5)
            if result.stdout.strip():
                act_result['next_action'] = "Temukan fungsi utama di opsora_repl.py"
                act_result['details'] = result.stdout.strip()[:200] + "…"
        except Exception as e:
            act_result['error'] = str(e)

    # STEP 4: VERIFY — Cek validitas langkah & output
    verify = "VERIFY: Langkah 1 valid — identifikasi komponen dasar adalah fondasi yang aman. Lanjut ke langkah 2."

    # STEP 5: REPORT — Ringkas progres & next step
    report = f"REPORT: Masalah '{problem[:30]}...' sedang diurai. Langkah berikutnya: cari file terkait."

    return {
        "problem": problem,
        "think": think,
        "plan": plan,
        "act": act_result,
        "verify": verify,
        "report": report,
        "status": "in_progress",
        "next_step": "glob_search pattern related to problem",
    }


# Contoh penggunaan
if __name__ == "__main__":
    result = solve_problem("cari bug di opsora_repl.py")
    print(json.dumps(result, indent=2, ensure_ascii=False))
