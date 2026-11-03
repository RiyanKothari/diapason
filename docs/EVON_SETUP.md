# Running Evon for Diapason (free, ~15 minutes)

Evon v3.3 has no hosted API (Hugging Face lists no inference provider), and the smallest 4-bit copy
(18.1 GB) is larger than a 16 GB laptop's RAM. The free path is a Kaggle notebook with two T4 GPUs
serving it behind a password-protected public URL.

## Once

1. **Hugging Face:** sign in at huggingface.co and open
   https://huggingface.co/gnani/gnani-evon-v3.3-30B-A3B → accept the access conditions (the challenge
   requires it).
2. **Kaggle:** sign up at kaggle.com and verify your phone number (Settings → Phone verification).
   Without it, notebooks get no GPU and no internet.

## Each session

1. kaggle.com → **Create → New Notebook** → **File → Import Notebook** → upload
   `deploy/evon_kaggle.ipynb` from this repo.
2. Right panel → **Session options**: **Accelerator = GPU T4 x2**, **Internet = On**.
3. **Run All**. The first run compiles llama.cpp (~30 min on Kaggle's 4 CPUs) while the model downloads in parallel. It then saves `llama-server-cuda75.tgz` in the Output panel: download it, create a Kaggle Dataset from it (Datasets → New), and attach it to the notebook (Add Input). Later sessions restore it and are ready in ~5 min.
4. Cell 5 prints three lines. Paste them over the `EVON_` lines in `Agnani/.env`:
   ```
   EVON_BASE_URL=https://<random>.trycloudflare.com/v1
   EVON_API_KEY=<random key>
   EVON_MODEL=evon
   ```
5. On your laptop: `.venv/Scripts/diapason doctor --live` → the Evon line should say OK.
6. Leave the Kaggle tab open while testing. The URL and key change every session; repeat step 4.

## Notes

- Free quota: ~30 GPU hours/week; a session lasts up to 12 hours.
- The API key stops strangers from using your tunnel. Never commit `.env`.
- Diapason disables Evon's reasoning traces (`enable_thinking: false`) for speed and clean JSON.
- Evon calls cost no Gnani credits; only Prisma (STT) and Timbre (TTS) draw on the 5,000.
