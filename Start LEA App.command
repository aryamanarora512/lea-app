#!/bin/bash
# Double-click to launch the LEA app (target screener + data loader) in your browser.
cd "$(dirname "$0")"
exec streamlit run app.py
