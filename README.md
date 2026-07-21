# 🔐 Smart Door Lock Using AI Face Recognition

A smart door access control system using **SCRFD** for face detection and **ArcFace (iResNet50 Fine-tuning)** for face recognition. The iResNet50 model was fine-tuned from the original InsightFace backbone for academic and research purposes, so its recognition performance may not be as accurate or robust as the official pretrained InsightFace models.

The project integrates **ESP32-CAM**, **FastAPI**, **MySQL**, and a web dashboard to provide real-time face registration, recognition, access monitoring, and automatic door unlocking.

> **Note**
>
> The Google Drive folder also provides the original **InsightFace backbone weights** and a mini version of the **CASIA-WebFace dataset** (approximately 1000 identities). These files are optional and are intended for users who want to reproduce the training process, perform transfer learning, or further fine-tune the ArcFace model.
>
> If you only want to run the face recognition system, downloading `last_backbone.pth` is sufficient.

---

# Features

## User Features

* Real-time camera preview from ESP32-CAM
* Automatic face verification every 2 seconds
* Face recognition using ArcFace
* Automatic door unlock when authentication succeeds
* Access denied for unknown users

---

## Administrator Features

* Register new users from ESP32-CAM
* Manage registered faces
* Search users by name
* Delete users
* Access log monitoring
* Web-based Admin Dashboard

---

# System Architecture

<img width="1537" height="1023" alt="Image" src="https://github.com/user-attachments/assets/7cb61836-fdee-4135-a3be-40de1a23f299" />

---

# Technologies

| Category         | Technology                      |
| ---------------- | ------------------------------- |
| Backend          | FastAPI                         |
| Deep Learning    | PyTorch                         |
| Face Detection   | SCRFD                           |
| Face Recognition | ArcFace (iResNet50 Fine-tuning) |
| Image Processing | OpenCV                          |
| Database         | MySQL                           |
| Embedded System  | ESP32-CAM                       |
| Frontend         | HTML, CSS, JavaScript           |
| Communication    | HTTP                            |

---

# Download Models and Dataset

Large files are not included in this repository due to GitHub size limitations.

Google Drive:

https://drive.google.com/drive/folders/1RXET4TYlMxxSD6FTva1lU4smaf3QEEp-?usp=sharing

---

## Contents

### work_dirs

Contains training checkpoints.

Only one file is required for inference:

```text
work_dirs/

└── 1000_phase3_full/

    └── last_backbone.pth
```

This file is mandatory because the AI Server loads this model for face recognition.

Other checkpoints are only provided for reference and analysis of the training process.

---

### pretrained

Contains pretrained ArcFace backbone models from InsightFace.

Files inside this folder are only needed if you want to perform transfer learning or retrain the model.

Includes:

```text
pretrained/

├── backbone.pth

└── insightface_backbone_full.zip
```

---

### dataset_images_1000

Mini version of the CASIA-WebFace dataset.

Contains approximately 1000 identities extracted and reorganized from CASIA-WebFace.

Used for ArcFace fine-tuning experiments.

---

# ⚙ Installation

## 1. Clone Repository

```bash
git clone https://github.com/hoangdtu01/Smart-Door-Lock-Using-AI-Face-Recognition.git

cd Smart-Door-Lock-Using-AI-Face-Recognition
```

---

## 2. Download Required Files

Download:

```text
work_dirs.zip
```

from Google Drive.

Extract and place:

```text
last_backbone.pth
```

into

```text
arcface_torch/work_dirs/1000_phase3_full/
```

Result:

```text
arcface_torch/

└── work_dirs/

    └── 1000_phase3_full/

        └── last_backbone.pth
```

---

## 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 4. Create Database

Open MySQL.

Create database:

```sql
CREATE DATABASE smart_door_ai;
```

Import:

```text
database/smart_door_ai.sql
```

---

## 5. Configure Database Connection

Edit:

```text
ai_server/db.py
```

Configure:

```python
host="localhost"

user="root"

password=""

database="smart_door_ai"
```

---

## 6. Run AI Server

```bash
cd ai_server

uvicorn main:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

---

## 7. Upload ESP32-CAM Firmware

Firmware source code:

```text
esp32_cam/

└── esp32_cam.ino
```

Open the file using Arduino IDE.

Edit WiFi credentials:

```cpp
const char* ssid = "...";

const char* password = "...";
```

Select board:

```text
AI Thinker ESP32-CAM
```

Upload firmware.

After uploading successfully:

Disconnect IO0 from GND.

Press RST button.

---

# 📂 Project Structure

```text
ai_server/

arcface_torch/

database/

esp32_cam/

web_dashboard/

requirements.txt

README.md

LICENSE
```

---

# 📄 License

This project is licensed under the MIT License.

---

# 👨‍💻 Author

Trần Văn Hoàng - hoangdtu01@gmail.com

Vietnam - Korea University of Information and Communication Technology (VKU)

GitHub

https://github.com/hoangdtu01

```
```
