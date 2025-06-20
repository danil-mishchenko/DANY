#!/bin/bash

# Говорим скрипту остановиться, если любая команда завершится с ошибкой
set -e

# 1. Устанавливаем утилиты для скачивания (wget) и распаковки (xz-utils)
apt-get update -y
apt-get install -y wget xz-utils

# 2. Скачиваем статический билд ffmpeg
# (Ссылка может устареть, всегда можно найти актуальную на https://johnvansickle.com/ffmpeg/)
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
wget -O ffmpeg.tar.xz $FFMPEG_URL

# 3. Создаем временную папку и распаковываем архив
mkdir ffmpeg-static
tar -xf ffmpeg.tar.xz -C ffmpeg-static --strip-components=1

# 4. Создаем папку /bin в корне проекта и копируем туда нужные файлы
mkdir -p bin
cp ffmpeg-static/ffmpeg bin/
cp ffmpeg-static/ffprobe bin/

# 5. Устанавливаем Python-зависимости, как и раньше
pip install -r requirements.txt

echo "ffmpeg и ffprobe успешно установлены в папку bin"
