from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return 'Bot is running!'

def run():
    app.run(host='0.0.0.0', port=8080, threaded=True)

t = threading.Thread(target=run)
t.daemon = True  # Это сделает поток демоном, чтобы он завершился с программой
t.start()
