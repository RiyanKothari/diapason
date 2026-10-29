# %% [markdown]
# # Serve Gnani Evon v3.3 for Bhool Bhulaiya (free, on Kaggle)
#
# Load this into Kaggle with **File → Import Notebook** → upload `deploy/evon_kaggle.ipynb` (generated from
# `deploy/evon_kaggle.py` by `python deploy/build_notebook.py`). Re-importing replaces every cell at once.
#
# **Before running:** Settings (right panel) → **Accelerator: GPU T4 x2** and **Internet: On**
# (internet needs a phone-verified Kaggle account). Then **Run All** in an interactive session and leave
# this tab open: the server lives as long as the notebook runs (up to 12 h; ~30 GPU h/week free).
#
# Evon v3.3 is a 30B mixture-of-experts with ~3.5B parameters active per token, so a 4-bit GGUF
# (IQ4_XS, 18.4 GB) split across the two T4s serves it at interactive speed.
#
# Also accept the access conditions on https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B (the
# challenge asks for it). If the GGUF repo ever becomes gated, add a Kaggle secret named `HF_TOKEN`.

# %%
import os, re, secrets, subprocess, time, json, urllib.error, urllib.request
print(subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv"], capture_output=True, text=True).stdout)

# %% Start the 18.4 GB model download in the background, so it overlaps with the build below.
import glob, shutil, threading
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"          # keep the build log readable
subprocess.run("pip -q install -U huggingface_hub", shell=True, check=True)
from huggingface_hub import hf_hub_download
token = None
try:
    from kaggle_secrets import UserSecretsClient
    token = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:
    pass
download = {}
def _download():
    try:   # /tmp sits outside the 20 GB /kaggle/working limit
        download["path"] = hf_hub_download("luminenio/gnani-evon-v3.3-30B-A3B-GGUF", "gnani-evon-v3.3-30B-A3B-IQ4_XS.gguf",
                                           local_dir="/tmp/models", token=token)
    except Exception as e:
        download["error"] = e
downloader = threading.Thread(target=_download, daemon=True)
downloader.start()
print("model download started in the background")

# %% llama.cpp with CUDA for the T4 (compute capability 7.5): reuse a cached build, else compile (~30 min).
# Compiling burns ~30 min of GPU quota every session. After the first build this cell saves
# /kaggle/working/llama-server-cuda75.tgz: download it (Output panel), create a Kaggle Dataset from it,
# and attach that dataset (Add Input) to this notebook. Every later session then skips the compile.
LC, CACHE = "/kaggle/working/llama.cpp", "llama-server-cuda75.tgz"
BIN = f"{LC}/build/bin"
if not os.path.exists(f"{BIN}/llama-server"):
    tgz = glob.glob(f"/kaggle/input/**/{CACHE}", recursive=True)
    unpacked = glob.glob("/kaggle/input/**/bin/llama-server", recursive=True)   # Kaggle may auto-extract it
    if tgz or unpacked:
        os.makedirs(f"{LC}/build", exist_ok=True)
        if tgz:
            subprocess.run(["tar", "-xzf", tgz[0], "-C", f"{LC}/build"], check=True)
        else:
            shutil.copytree(os.path.dirname(unpacked[0]), BIN)
        subprocess.run(f"chmod +x {BIN}/*", shell=True, check=True)
        print("restored cached llama-server from", (tgz or unpacked)[0])
    else:
        if not os.path.exists(f"{LC}/CMakeLists.txt"):
            subprocess.run(f"git clone --depth 1 https://github.com/ggml-org/llama.cpp {LC}", shell=True, check=True)
        shutil.rmtree(f"{LC}/build", ignore_errors=True)        # clear a failed configure
        # Kaggle's CUDA toolkit ships without the libcuda.so link CMake looks for ("CUDA::cuda_driver ... not
        # found"). Point CMake at the stub (build time) or the real driver library, whichever exists.
        found = [p for pat in ("/usr/local/cuda/lib64/stubs/libcuda.so", "/usr/local/cuda/targets/x86_64-linux/lib/stubs/libcuda.so",
                               "/usr/lib/x86_64-linux-gnu/libcuda.so", "/usr/lib/x86_64-linux-gnu/libcuda.so.1",
                               "/usr/local/nvidia/lib64/libcuda.so.1") for p in glob.glob(pat)]
        print("libcuda for linking:", found[0] if found else "none found")
        driver = f"-DCUDA_cuda_driver_LIBRARY={found[0]}" if found else "-DGGML_CUDA_NO_VMM=ON"
        subprocess.run(f"cd {LC} && cmake -B build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=75 {driver} "
                       "-DLLAMA_CURL=OFF -DCMAKE_BUILD_TYPE=Release && cmake --build build -j 4 --target llama-server",
                       shell=True, check=True)
        subprocess.run(["tar", "-czf", f"/kaggle/working/{CACHE}", "-C", f"{LC}/build", "bin"], check=True)
        print(f"saved /kaggle/working/{CACHE} ({os.path.getsize(f'/kaggle/working/{CACHE}') / 1e6:.0f} MB): "
              "make it a Kaggle Dataset and attach it to skip this build next time")
print("llama-server ready")

# %% Wait for the model download (started above) to finish.
downloader.join()
if "error" in download:
    raise download["error"]
MODEL = download["path"]
print(MODEL, round(os.path.getsize(MODEL) / 1e9, 1), "GB")

# %% Start the OpenAI-compatible server, protected by a random API key (the tunnel is public).
# Stop anything left over from an earlier run of this cell, so Run All is always safe to repeat.
for name in ("llama-server", "cloudflared"):
    subprocess.run(["pkill", "-f", name])   # no shell: pkill would match its own sh -c line
time.sleep(2)
API_KEY = secrets.token_urlsafe(24)
server = subprocess.Popen(
    ["/kaggle/working/llama.cpp/build/bin/llama-server", "-m", MODEL, "--alias", "evon",
     "--host", "127.0.0.1", "--port", "8080", "-ngl", "99", "--split-mode", "layer",
     "-c", "16384", "--parallel", "4", "--jinja", "--api-key", API_KEY],
    env={**os.environ, "LD_LIBRARY_PATH": f"{BIN}:" + os.environ.get("LD_LIBRARY_PATH", "")},   # cached libs
    stdout=open("/kaggle/working/server.log", "w"), stderr=subprocess.STDOUT,
    start_new_session=True)   # so stopping a cell (SIGINT to the kernel's process group) leaves Evon running
for _ in range(180):
    try:
        if json.load(urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2)).get("status") == "ok":
            break
    except Exception:
        pass
    time.sleep(5)
else:
    print(open("/kaggle/working/server.log").read()[-3000:])
    raise RuntimeError("server did not become healthy; see log above")
print("Evon server healthy")

# %% Public HTTPS tunnel (Cloudflare quick tunnel: no account needed). The URL changes every session.
if not os.path.exists("/kaggle/working/cloudflared"):
    subprocess.run("wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 "
                   "-O /kaggle/working/cloudflared && chmod +x /kaggle/working/cloudflared", shell=True, check=True)
tunnel = subprocess.Popen(["/kaggle/working/cloudflared", "tunnel", "--url", "http://127.0.0.1:8080", "--no-autoupdate"],
                          stderr=open("/kaggle/working/tunnel.log", "w"), stdout=subprocess.DEVNULL,
                          start_new_session=True)
URL = None
for _ in range(60):
    m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open("/kaggle/working/tunnel.log").read())
    if m:
        URL = m.group(0)
        break
    time.sleep(2)
assert URL, "tunnel did not start; see /kaggle/working/tunnel.log"
print("Paste these three lines into Agnani/.env (replace the existing EVON_ lines):\n")
print(f"EVON_BASE_URL={URL}/v1")
print(f"EVON_API_KEY={API_KEY}")
print("EVON_MODEL=evon")

# %% Smoke test: first the model itself (local), then the public URL exactly as Bhool Bhulaiya calls it.
# A new trycloudflare hostname can take up to a minute to resolve in DNS, so the public check retries.
def ask(base):
    req = urllib.request.Request(f"{base}/v1/chat/completions", method="POST",
        headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
        data=json.dumps({"model": "evon", "max_tokens": 60, "temperature": 0,
                         "chat_template_kwargs": {"enable_thinking": False}, "response_format": {"type": "json_object"},
                         "messages": [{"role": "user", "content": 'Reply with JSON {"say": "<a short Hinglish greeting>"}'}]}).encode())
    t0 = time.time()
    out = json.load(urllib.request.urlopen(req, timeout=120))
    return round(time.time() - t0, 2), out["choices"][0]["message"]["content"]

try:
    secs, text = ask("http://127.0.0.1:8080")
except urllib.error.HTTPError as e:
    print(e.read().decode()[:1000], "\n", open("/kaggle/working/server.log").read()[-2000:])
    raise
print(f"model OK (local): {secs}s -> {text}")
for attempt in range(12):
    try:
        secs, text = ask(URL)
        print(f"public URL OK: {secs}s -> {text}\nEvon is ready. Paste the three lines above into .env")
        break
    except Exception as e:
        print(f"public URL not reachable yet ({type(e).__name__}); retrying in 10 s...")
        time.sleep(10)
else:
    print("Public URL still not reachable from inside Kaggle. It usually works from your laptop anyway: "
          "paste the lines into .env and run `bhool doctor --live`.")

# %% Keep the session alive and show throughput. Stop this cell (or the session) to shut Evon down.
while True:
    time.sleep(300)
    log = open("/kaggle/working/server.log").read()
    speeds = re.findall(r"eval time .*?([\d.]+) tokens per second", log)
    print(time.strftime("%H:%M"), "alive; last generation speed:", speeds[-1] if speeds else "n/a", "tok/s")
