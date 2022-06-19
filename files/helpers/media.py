from PIL import Image, ImageOps
from PIL.ImageSequence import Iterator
from webptools import gifwebp
import subprocess
import os
from flask import abort, g
import requests
import time
from .const import *


def process_files():
	body = ''
	if request.files.get("file") and request.headers.get("cf-ipcountry") != "T1":
		files = request.files.getlist('file')[:4]
		for file in files:
			if file.content_type.startswith('image/'):
				name = f'/images/{time.time()}'.replace('.','') + '.webp'
				file.save(name)
				url = process_image(name)
				body += f"\n\n![]({url})"
			elif file.content_type.startswith('video/'):
				body += f"\n\n{process_video(file)}"
			elif file.content_type.startswith('audio/'):
				body += f"\n\n{process_audio(file)}"
			else:
				body += f"\n\n{process_other(file)}"
	return body


def process_other(file):
	req = requests.request("POST", "https://pomf2.lain.la/upload.php", files={'files[]': file}, timeout=20).json()
	return req['files'][0]['url']


def process_audio(file):
	name = f'/audio/{time.time()}'.replace('.','') + '.mp3'
	file.save(name)

	if os.stat(name).st_size > UPLOAD_SIZE_LIMIT_NORMAL:
		with open(name, 'rb') as f:
			os.remove(name)
			req = requests.request("POST", "https://pomf2.lain.la/upload.php",
				files={'files[]': f}, timeout=20).json()
		return req['files'][0]['url']

	return f'{SITE_FULL}{name}'


def process_video(file):
	old = f'/videos/{time.time()}'.replace('.','')
	new = old + '.mp4'
	file.save(old)

	# TODO: Assumes file extension is accurate to container & codec.
	#       Actually verify what it is first (ffprobe?).
	if file.filename.split('.')[-1].lower() == 'webm':
		if os.stat(old).st_size <= UPLOAD_SIZE_LIMIT_NORMAL:
			subprocess.run(["ffmpeg", "-y", "-loglevel", "warning", "-i", old, "-map_metadata", "-1", new], check=True, stderr=subprocess.STDOUT)
		elif not UPLOAD_REJECT_WEBM:
			file.save(new)
		else:
			abort(413)
	else:
		subprocess.run(["ffmpeg", "-y", "-loglevel", "warning", "-i", old, "-map_metadata", "-1", "-c:v", "copy", "-c:a", "copy", new], check=True)
	
	os.remove(old)
	size = os.stat(new).st_size
	if os.stat(new).st_size > UPLOAD_SIZE_LIMIT_NORMAL:
		with open(new, 'rb') as f:
			os.remove(new)
			req = requests.request("POST", "https://pomf2.lain.la/upload.php",
				files={'files[]': f}, timeout=20).json()
		return req['files'][0]['url']

	return f'{SITE_FULL}{new}'


def process_image(filename=None, resize=0):
	size = os.stat(filename).st_size

	if resize == 100: patron = False
	else: patron = g.v.patron

	if size > UPLOAD_SIZE_LIMIT_PATRON or (not patron and size > UPLOAD_SIZE_LIMIT_NORMAL):
		os.remove(filename)
		abort(413)

	i = Image.open(filename)

	if resize and i.width > resize:
		try: subprocess.run(["convert", filename, "-coalesce", "-resize", f"{resize}>", filename])
		except: pass
	elif i.format.lower() != "webp":

		exif = i.getexif()
		for k in exif.keys():
			if k != 0x0112:
				exif[k] = None
				del exif[k]
		i.info["exif"] = exif.tobytes()

		if i.format.lower() == "gif":
			gifwebp(input_image=filename, output_image=filename,
				option="-mixed -metadata none -f 100 -mt -m 6")
		else:
			i = ImageOps.exif_transpose(i)
			i.save(filename, format="WEBP", method=6)

	return filename
