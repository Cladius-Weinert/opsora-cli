from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE_ROOT = Path("/root")
OPSORA_DIR = WORKSPACE_ROOT / ".opsora"

# Safety constants (copied from opsora_v2.py)
SENSITIVE_PATHS = {".aws", ".ssh", ".gnupg", ".tccli"}
SENSITIVE_FILES = {"render.env", "secrets.env", ".opsora_env", "credentials", ".env",
                   "cloud-manager.sh", ".bash_history", ".netrc", ".pgpass"}
CREDENTIAL_KEYWORDS = ["api_key", "secret_key", "password", "token", "access_key"]
TOOL_MAX_OUTPUT = 30_000


def _safe_read_file(filepath: Path) -> str:
    """Read file with safety checks similar to opsora_v2.py."""
    try:
        if not filepath.is_absolute():
            filepath = WORKSPACE_ROOT / filepath
        resolved = filepath.resolve()
        # Safety checks
        if SENSITIVE_PATHS & set(resolved.parts):
            return "BLOCKED: folder credential (.aws/.ssh/.gnupg) gak bisa dibaca."
        if resolved.name in SENSITIVE_FILES or resolved.name.startswith(".env"):
            return f"BLOCKED: {resolved.name} berisi credentials."
        content = resolved.read_text(encoding="utf-8", errors="replace")
        return content[:TOOL_MAX_OUTPUT]
    except Exception as e:
        return f"ERROR: {e}"


def _safe_glob_search(pattern: str, base: str = ".") -> List[str]:
    """Glob search with safety."""
    try:
        if not Path(base).is_absolute():
            base_path = WORKSPACE_ROOT / base
        else:
            base_path = Path(base)
        # Ensure we stay within workspace
        if not str(base_path.resolve()).startswith(str(WORKSPACE_ROOT)):
            return ["ERROR: Base directory outside workspace"]
        files = []
        for p in base_path.rglob(pattern):
            if str(p.resolve()).startswith(str(WORKSPACE_ROOT)):
                files.append(str(p))
        return files[:20]  # Limit results
    except Exception as e:
        return [f"ERROR: {e}"]


def _safe_grep_search(pattern: str, path: str = ".", file_type: Optional[str] = None) -> List[str]:
    """Grep search with safety."""
    try:
        if not Path(path).is_absolute():
            search_path = WORKSPACE_ROOT / path
        else:
            search_path = Path(path)
        # Ensure we stay within workspace
        if not str(search_path.resolve()).startswith(str(WORKSPACE_ROOT)):
            return ["ERROR: Search path outside workspace"]
        # Build grep command
        cmd = ["grep", "-r", "--include=*" + (file_type or "*"), pattern, str(search_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode not in (0, 1):
            return [f"ERROR: grep failed: {result.stderr}"]
        lines = result.stdout.strip().split('\n')
        # Format like: /path/to/file:line_number:content
        return [line for line in lines if line][:20]
    except subprocess.TimeoutExpired:
        return ["ERROR: grep timeout"]
    except Exception as e:
        return [f"ERROR: {e}"]


def solve_problem(
    problem: str,
    context: Optional[str] = None,
    history: List[Dict[str, Any]] = None,
    max_steps: int = 5,
) -> Dict[str, Any]:
    """
    Sistem problem solving terstruktur berbasis THINK → PLAN → ACT → VERIFY → REPORT.
    Enhanced to actually perform basic file and code exploration.

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

    # Extract potential file names (ending with .py)
    file_candidates = re.findall(r'\b[\w/]+\.(?:py)\b', problem)
    # Also look for potential error messages
    error_indicators = ['error', 'exception', 'failed', 'fail', 'tidak bisa', 'gagal', 'error']
    has_error = any(word in problem.lower() for word in error_indicators)

    # STEP 2: PLAN — Rencanakan langkah konkret
    plan_steps = []
    if file_candidates:
        plan_steps.append("PLAN: 1. Cari file yang disebutkan di seluruh workspace.")
        plan_steps.append("PLAN: 2. Jika file ditemukan, baca isinya.")
        plan_steps.append("PLAN: 3. Cari fungsi, kelas, atau kode yang relevan dalam file tersebut.")
    elif has_error:
        plan_steps.append("PLAN: 1. Ekstrak pesan error dari masalah.")
        plan_steps.append("PLAN: 2. Cari pesan error tersebut di seluruh kode sumber.")
        plan_steps.append("PLAN: 3. Analisis konteks sekitar kemunculan error.")
    else:
        plan_steps = [
            "PLAN: 1. Identifikasi komponen kunci dari masalah",
            "PLAN: 2. Cari file atau kode terkait menggunakan glob/grep",
            "PLAN: 3. Baca dan analisis isi file yang relevan",
            "PLAN: 4. Verifikasi asumsi atau hasil sementara",
            "PLAN: 5. Ringkas solusi dalam 1–3 kalimat"
        ]

    # Default values for act result
    act_result = {
        "step": 1,
        "action": "Inisialisasi analisis",
        "output": "Memulai proses penyelesaian masalah",
        "details": "",
        "next_action": "Lanjutkan ke langkah berikutnya dalam rencana",
    }

    # STEP 3: ACT — Jalankan langkah pertama (mencoba menggunakan tools)
    try:
        if file_candidates:
            # Try to find the first candidate file
            found_files = []
            for cf in file_candidates[:3]:  # Limit to first 3 candidates
                # Try exact path first
                test_path = Path(cf)
                if not test_path.is_absolute():
                    test_path = WORKSPACE_ROOT / cf
                if test_path.is_file():
                    found_files.append(str(test_path))
                else:
                    # Search for it
                    matches = _safe_glob_search(cf, ".")
                    if matches and not any(m.startswith("ERROR:") for m in matches):
                        found_files.extend([m for m in matches if not m.startswith("ERROR:")])
            
            if found_files:
                # Take the first unique file
                target_file = list(dict.fromkeys(found_files))[0]  # Preserve order, remove duplicates
                # Read the file
                content = _safe_read_file(Path(target_file))
                act_result = {
                    "step": 1,
                    "action": f"Membaca file yang ditemukan: {target_file}",
                    "output": content[:200] + ("..." if len(content) > 200 else ""),
                    "details": f"File length: {len(content)} characters",
                    "next_action": "Telusuri fungsi atau kelas yang relevan dalam file ini" if not content.startswith(("ERROR:", "BLOCKED:")) else "File tidak dapat dibaca, coba pencarian teks"
                }
            else:
                # File not found, try searching for the name as text
                search_term = file_candidates[0]
                matches = _safe_grep_search(search_term, ".", "py")
                if matches and not any(m.startswith("ERROR:") for m in matches):
                    act_result = {
                        "step": 1,
                        "action": f"Mencari referensi ke '{search_term}' dalam file Python",
                        "output": "\n".join(matches[:5]),
                        "details": f"Found {len(matches)} matches",
                        "next_action": "Periksa file yang mengandung referensi ini"
                    }
                else:
                    act_result = {
                        "step": 1,
                        "action": f"Mencari file '{file_candidates[0]}'",
                        "output": "File tidak ditemukan melalui pencarian langsung atau pola.",
                        "details": "Mencoba pendekatan alternatif",
                        "next_action": "Gunakan pencarian konten lebih luas atau periksa nama file yang berbeda"
                    }
        elif has_error:
            # Try to extract error-like text
            # Simple approach: look for quoted strings or capitalized words
            error_patterns = [
                r'"([^"]*error[^"]*)"',
                r"'([^']*error[^']*)'",
                r'\b[A-Z][a-z]+Error\b',
                r'\b[a-z]+_failed\b',
                r'\bfailed\b',
                r'\berror\b'
            ]
            error_terms = []
            for pat in error_patterns:
                matches = re.findall(pat, problem, re.IGNORECASE)
                if matches:
                    error_terms.extend(matches)
            if error_terms:
                search_term = error_terms[0]
                matches = _safe_grep_search(search_term, ".", "py")
                if matches and not any(m.startswith("ERROR:") for m in matches):
                    act_result = {
                        "step": 1,
                        "action": f"Mencari kesalahan yang disebutkan: '{search_term}'",
                        "output": "\n".join(matches[:5]),
                        "details": f"Found {len(matches)} matches",
                        "next_action": "Periksa konteks sekitar kecocokan ini untuk penyebab akar"
                    }
                else:
                    act_result = {
                        "step": 1,
                        "action": f"Mencari kesalahan: '{search_term}'",
                        "output": "Tidak ditemukan kecocokan untuk istilah kesalahan ini.",
                        "details": "Mencoba variasi lain dari pesan kesalahan",
                        "next_action": "Coba cari dengan kata kunci yang lebih umum atau periksa log jika tersedia"
                    }
            else:
                # Fallback to general search
                plan_steps = [
                    "PLAN: 1. Lakukan pencarian umum untuk istilah terkait masalah",
                    "PLAN: 2. Analisis hasil pencarian untuk pola yang relevan",
                    "PLAN: 3. Berikan rekomendasi berdasarkan temuan"
                ]
                # Use a generic search for nouns in the problem
                words = re.findall(r'\b[a-zA-Z]{4,}\b', problem)
                if words:
                    search_term = words[0]
                    matches = _safe_grep_search(search_term, ".", "py")
                    if matches and not any(m.startswith("ERROR:") for m in matches):
                        act_result = {
                            "step": 1,
                            "action": f"Mencari istilah kunci: '{search_term}'",
                            "output": "\n".join(matches[:3]),
                            "details": f"Found {len(matches)} matches",
                            "next_action": "Periksa file yang relevan untuk kontekstual lebih dalam"
                        }
                    else:
                        act_result = {
                            "step": 1,
                            "action": f"Mencari istilah umum: '{search_term}'",
                            "output": "Tidak ditemukan kecocokan signifikan.",
                            "details": "Hasil pencarian terbatas",
                            "next_action": "Periksa konteks yang diberikan atau tanyakan klarifikasi"
                        }
                else:
                    act_result = {
                        "step": 1,
                        "action": "Analisis awal masalah",
                        "output": "Tidak cukup spesifikasi untuk tindakan otomatis.",
                        "details": "Masalah terlalu umum",
                        "next_action": "Berikan lebih banyak detail atau kontekstual tentang masalah"
                    }
        else:
            # No specific file or error, do a general search based on keywords
            # Extract nouns (simplified)
            words = re.findall(r'\b[a-zA-Z]{4,}\b', problem)
            if words:
                # Try first few words
                for word in words[:3]:
                    matches = _safe_grep_search(word, ".", "py")
                    if matches and not any(m.startswith("ERROR:") for m in matches):
                        act_result = {
                            "step": 1,
                            "action": f"Mencari istilah terkait: '{word}'",
                            "output": "\n".join(matches[:3]),
                            "details": f"Found {len(matches)} matches",
                            "next_action": "Periksa file yang relevan untuk memahami kontekstual"
                        }
                        break
                else:
                    # If no matches for any word, try a broader search
                    # Look for any significant word in the problem
                    significant_words = [w for w in words if w.lower() not in ['ini', 'yang', 'dengan', 'dari', 'untuk', 'adalah', 'merupakan', 'mencari', 'menemukan', 'membuat', 'mengubah']]
                    if significant_words:
                        word = significant_words[0]
                        matches = _safe_grep_search(word, ".", "py")
                        if matches and not any(m.startswith("ERROR:") for m in matches):
                            act_result = {
                                "step": 1,
                                "action": f"Mencari kata signifikant: '{word}'",
                                "output": "\n".join(matches[:3]),
                                "details": f"Found {len(matches)} matches",
                                "next_action": "Periksa hasil untuk relevansi"
                            }
                        else:
                            act_result = {
                                "step": 1,
                                "action": "Analisis awal berdasarkan kata kunci",
                                "output": "Tidak ditemukan kecocokan kode untuk kata kunci yang diberikan.",
                                "details": "Mungkin perlu kontekstual lebih spesifik",
                                "next_action": "Berikan nama file, fungsi, atau pesan error yang lebih spesifik"
                            }
                    else:
                        act_result = {
                            "step": 1,
                            "action": "Analisis awal masalah",
                            "output": "Tidak cukup kata kunci yang bermakna untuk pencarian.",
                            "details": "Masalah terlalu umum atau tidak spesifik",
                            "next_action": "Jelaskan masalah dengan lebih detail, termasuk file atau pesan error jika ada"
                        }
            else:
                act_result = {
                    "step": 1,
                    "action": "Analisis awal masalah",
                    "output": "Tidak ada kata kunci yang terdeteksi untuk pencarian.",
                    "details": "Masalah mungkin terlalu pendek atau tidak mengandung istilah teknis",
                    "next_action": "Berikan deskripsi yang lebih lengkap tentang apa yang Anda ingin capai atau masalah yang Anda hadapi"
                }
    except Exception as e:
        act_result = {
            "step": 1,
            "action": "Penanganan kesalahan selama tindakan",
            "output": f"ERROR: {str(e)}",
            "details": "Terjadi pengecualian yang tidak terduga",
            "next_action": "Periksa log atau coba lagi dengan input yang lebih sederhana"
        }

    # STEP 4: VERIFY — Cek validitas langkah & output
    verify = "VERIFY: "
    if act_result["output"].startswith("ERROR:") or act_result["output"].startswith("BLOCKED:"):
        verify += "Terdapat kesalahan atau pemblokiran saat menjalankan tindakan. Tidak dapat melanjutkan dengan otomatis."
    elif "tidak ditemukan" in act_result["output"].lower() or "not found" in act_result["output"].lower():
        verify += "Tindakan tidak menghasilkan hasil yang diharapkan. Pertimbangkan pendekatan alternatif atau periksa kembali masukan."
    elif len(act_result["output"]) > 20:
        verify += "Tindakan berhasil menghasilkan output yang dapat dianalisis. Lanjutkan ke evaluasi lebih dalam."
    else:
        verify += "Tindakan berjalan tetapi outputnya terbatas. Pertimbangkan untuk mendapatkan lebih banyak informasi."

    # STEP 5: REPORT — Ringkas progres & next step
    report_parts = [f"REPORT: Masalah '{problem[:50]}...'"]
    if file_candidates:
        report_parts.append(f"berkaitan dengan file yang disebutkan.")
    elif has_error:
        report_parts.append("terkait dengan pesan kesalahan atau masalah teknis.")
    else:
        report_parts.append("sedang dianalisis untuk tindakan lanjutan.")
    
    if not act_result["output"].startswith(("ERROR:", "BLOCKED:")) and len(act_result["output"]) > 10:
        report_parts.append(f" Temuan awal: {act_result['output'][:100]}{'...' if len(act_result['output']) > 100 else ''}")
    else:
        report_parts.append(" Tidak dapat memperoleh informasi awal yang berguna.")
    
    report_parts.append(f" Langkah selanjutnya yang disarankan: {act_result['next_action']}")
    report = " ".join(report_parts)

    return {
        "problem": problem,
        "think": think,
        "plan": "\n".join(plan_steps),
        "act": act_result,
        "verify": verify,
        "report": report,
        "status": "completed" if not (act_result["output"].startswith("ERROR:") or act_result["output"].startswith("BLOCKED:")) else "failed",
        "next_step": act_result["next_action"],
        "details": act_result.get("details", "")
    }


# Contoh penggunaan
if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        problem = " ".join(sys.argv[1:])
    else:
        problem = "cari bug di opsora_v2.py"
    result = solve_problem(problem)
    print(json.dumps(result, indent=2, ensure_ascii=False))