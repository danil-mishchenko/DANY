#!/bin/bash

# Устанавливаем системную зависимость ffmpeg
apt-get update && apt-get install -y ffmpeg

# Устанавливаем Python-зависимости
pip install -r requirements.txt
