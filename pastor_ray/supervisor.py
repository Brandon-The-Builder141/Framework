"""Hidden Windows login supervisor; only supervises Pastor Ray's own child."""
import logging
from logging.handlers import RotatingFileHandler
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pastor_ray.settings import ROOT


def main():
    instance = socket.socket()
    try:
        instance.bind(('127.0.0.1',18764))
    except OSError:
        return
    (ROOT/'logs').mkdir(exist_ok=True)
    logging.basicConfig(level=logging.INFO, handlers=[RotatingFileHandler(
        ROOT/'logs'/'supervisor.log',maxBytes=500000,backupCount=2)],
        format='%(asctime)s %(message)s')
    delay = 5
    python = str(__import__('pathlib').Path(sys.executable).with_name('python.exe'))
    while True:
        try:
            urllib.request.urlopen('http://127.0.0.1:11434/api/tags',timeout=3).close()
        except Exception:
            ollama = shutil.which('ollama')
            if ollama:
                subprocess.Popen([ollama,'serve'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        started = time.monotonic()
        with (ROOT/'logs'/'child.log').open('w',encoding='utf-8') as output:
            child = subprocess.Popen([python,'-m','pastor_ray.main'],cwd=ROOT.parent,
                                     stdout=output,stderr=output,creationflags=subprocess.CREATE_NO_WINDOW)
            logging.info('Started Pastor Ray child PID=%s',child.pid)
            code = child.wait()
        logging.info('Child exited code=%s; retry in %ss',code,delay)
        if time.monotonic()-started > 120:
            delay = 5
        time.sleep(delay)
        delay = min(delay*2,120)


if __name__=='__main__':
    main()
