# 🚀 Cloud Deployment Guide - AI Plot Layout Management

This project is fully containerized and production-ready. You can deploy it for free 24/7 on any of the following platforms.

---

## 🌟 Method 1: Render.com (Recommended - Free & Simplest)

Render will build and host both your React 19 Frontend and FastAPI Backend using the multi-stage `Dockerfile`.

### Steps:
1. **Push your code to GitHub**:
   - Create a GitHub repository (e.g. `ai-plot-layout`).
   - Push your project code to GitHub.
2. **Open Render**:
   - Go to [render.com](https://render.com) and log in with GitHub.
   - Click **New +** → **Web Service**.
   - Connect your `ai-plot-layout` repository.
3. **Configure & Deploy**:
   - **Name**: `ai-plot-layout`
   - **Runtime**: Select **Docker** (Render will automatically detect `Dockerfile` and `render.yaml`).
   - **Instance Type**: Select **Free**.
   - (Optional) In **Environment Variables**, you can add:
     - `OPENROUTER_API_KEY`: *(your key)* or
     - `GEMINI_API_KEY`: *(your free Gemini key)*
4. Click **Deploy Web Service**!
   - Render will build the React SPA, set up Python with OpenCV, and provide you with a permanent HTTPS link (e.g. `https://ai-plot-layout.onrender.com`).
   - **Whenever you push code changes to GitHub, Render automatically builds and updates your live site!**

---

## 🚂 Method 2: Railway.app (Fastest Build)

1. Go to [railway.app](https://railway.app) and sign up.
2. Click **New Project** → **Deploy from GitHub repo**.
3. Select this repository.
4. Railway will automatically detect `railway.json` and `Dockerfile`, build the container, and assign a public domain.
5. In **Settings** → **Networking**, click **Generate Domain**.

---

## ⚡ Method 3: Hugging Face Spaces (Free ML Hardware: 16 GB RAM + 2 vCPU)

Since this project uses Computer Vision (OpenCV) and OCR, Hugging Face Spaces offers generous free compute:
1. Go to [huggingface.co/spaces](https://huggingface.co/spaces) and click **Create new Space**.
2. Name your space and select **Docker** as the SDK (Blank template).
3. Clone the space repository locally or push your project to it.
4. Hugging Face will run the `Dockerfile` and give you a permanent `hf.space` link!

---

## 💻 Method 4: Self-Hosted Cloud VPS (DigitalOcean / AWS EC2 / Hetzner)

If deploying to an Ubuntu/Debian server:
```bash
# 1. Clone repository
git clone <your-repo-url>
cd "AI Plot Layout v2"

# 2. Start container with Docker Compose
docker compose up -d --build

# 3. View logs
docker compose logs -f
```
The app will be running on `http://<your-server-ip>:8000`.
