"""啟動台股分析工具。

工具使用自己的 Python 環境（.venv 資料夾），不受電腦上其他 Python 版本影響。
如果 .venv 不存在或損壞（例如當初建立它的 Python 被移除），會自動重新建立並安裝套件。
這個檔案只用 Python 內建模組，任何版本的 Python 都能執行它。
"""
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

URL = "http://localhost:8765"
HERE = Path(__file__).parent
VENV = HERE / ".venv"
VENV_PY = VENV / "Scripts" / "python.exe"
REQUIRED = "import streamlit, plotly, pandas, numpy"


def venv_ok() -> bool:
    if not VENV_PY.exists():
        return False
    try:
        return subprocess.run([str(VENV_PY), "-c", REQUIRED], capture_output=True, timeout=120).returncode == 0
    except OSError:
        return False


def windows_cert_bundle() -> str:
    """匯出 Windows 信任的憑證給 pip 用（防毒軟體做 HTTPS 掃描時，pip 預設的憑證會驗證失敗）。"""
    pem = Path(tempfile.gettempdir()) / "stock_tool_certs.pem"
    certs = []
    for store in ("ROOT", "CA"):
        for cert, enc, _ in ssl.enum_certificates(store):
            if enc == "x509_asn":
                certs.append(ssl.DER_cert_to_PEM_cert(cert))
    pem.write_text("".join(certs), encoding="ascii")
    return str(pem)


def build_venv() -> bool:
    print("正在建立工具專屬的 Python 環境並安裝套件（第一次約需 3～5 分鐘）…\n")
    if VENV.exists():
        shutil.rmtree(VENV, ignore_errors=True)
    if subprocess.call([sys.executable, "-m", "venv", str(VENV)]) != 0:
        return False
    cmd = [str(VENV_PY), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(HERE / "requirements.txt")]
    if os.name == "nt":
        cmd[4:4] = ["--cert", windows_cert_bundle()]
    return subprocess.call(cmd) == 0 and venv_ok()


def main() -> int:
    if not venv_ok() and not build_venv():
        print("\n建立環境失敗。請確認網路連線，或把上面的錯誤訊息貼給 Claude。")
        return 1
    print("台股分析工具啟動中，瀏覽器會自動打開 " + URL)
    print("使用完畢後關閉這個視窗即可結束程式。\n")
    threading.Timer(4, webbrowser.open, args=[URL]).start()
    try:
        return subprocess.call([str(VENV_PY), "-m", "streamlit", "run", str(HERE / "app.py")], cwd=HERE)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
