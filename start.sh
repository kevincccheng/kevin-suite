#!/bin/bash
cd ~/projects/kevin-suite

# Kill anything already on port 8502
lsof -ti :8502 | xargs kill -9 2>/dev/null || true

source venv/bin/activate
nohup streamlit run app.py --server.port 8502 --server.headless true > /tmp/streamlit.log 2>&1 &

sleep 10
open http://localhost:8502
